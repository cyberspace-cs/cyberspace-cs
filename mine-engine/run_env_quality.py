#!/usr/bin/env python3
"""环境四维体检：一键检查埋雷引擎产出的题池是否健康。

用法
----
    python run_env_quality.py                          # 体检 datasets/ 下全部样本
    python run_env_quality.py --cap 0.3                # 收紧单类别占比上限
    python run_env_quality.py --json                   # 机读输出
    python run_env_quality.py --gold results.json      # 带上黄金解答自测结果（正确性维）
    python run_env_quality.py --reference real/        # 带上真实任务锚定集（忠实度维）

体检依据：arXiv:2606.12191 的四维（正确性 / 多样性 / 复杂性 / 忠实度）
        + arXiv:2606.05405 (AWM) 的 blocked rate 与类别上限。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.analytics import (  # noqa: E402
    category_distribution,
    env_quality_report,
)

DATASETS = "datasets"


def load_tasks(root: str = DATASETS) -> list:
    """从 datasets/sample-*/ 读取真实格式的样本。"""
    tasks = []
    for d in sorted(glob.glob(os.path.join(root, "sample-*"))):
        meta_p = os.path.join(d, "meta.json")
        if not os.path.exists(meta_p):
            continue
        try:
            meta = json.load(open(meta_p, encoding="utf-8"))
        except Exception:
            continue

        source = ""
        planted = meta.get("planted")
        if planted:
            p = os.path.join(d, planted)
            if os.path.exists(p):
                source = open(p, encoding="utf-8").read()
        if not source:
            for sol in glob.glob(os.path.join(d, "**", "*.sol"), recursive=True):
                source += open(sol, encoding="utf-8").read()

        issues = meta.get("issues") or []
        types = meta.get("ground_truth_types") or [
            i.get("vuln_type") for i in issues if i.get("vuln_type")
        ]
        operators = [i.get("operator") for i in issues if i.get("operator")]
        sev = [i.get("severity") for i in issues if i.get("severity")]

        tasks.append({
            "task_id": meta.get("sample_id") or os.path.basename(d),
            "source": source,
            "vuln_type": types,
            "operators": operators,
            "severities": sev,
            # meta 里 difficulty 是 1..5 档，difficulty_histogram 会自动归一化
            "difficulty": (issues[0].get("difficulty") if issues else None),
            "decoy": not bool(types),   # 无 ground truth = 诱饵题（正确做法是空报告）
        })
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser(description="环境四维体检")
    ap.add_argument("--root", default=DATASETS, help="样本根目录（默认 datasets/）")
    ap.add_argument("--cap", type=float, default=0.4, help="单类别占比上限（默认 0.4）")
    ap.add_argument("--gold", help="黄金解答自测结果 JSON（算 blocked rate）")
    ap.add_argument("--reference", help="真实任务锚定集目录（算忠实度）")
    ap.add_argument("--json", action="store_true", help="输出机读 JSON")
    args = ap.parse_args()

    tasks = load_tasks(args.root)
    if not tasks:
        print(f"[!] 在 {args.root}/ 下没找到任何 sample-*/meta.json", file=sys.stderr)
        return 1

    gold = None
    if args.gold:
        try:
            gold = json.load(open(args.gold, encoding="utf-8"))
            if isinstance(gold, dict):
                gold = gold.get("results", [])
        except Exception as e:
            print(f"[!] 读取 --gold 失败：{e}", file=sys.stderr)

    ref = None
    if args.reference:
        ref = load_tasks(args.reference)
        if not ref:
            print(f"[!] {args.reference}/ 下没有可用样本", file=sys.stderr)
            ref = None

    report = env_quality_report(tasks, gold_results=gold, reference_tasks=ref, cap=args.cap)

    if args.json:
        print(json.dumps(dict(report), ensure_ascii=False, indent=2))
        return 0

    dims = report["dimensions"]
    zh = {
        "correctness": "正确性",
        "diversity": "多样性",
        "complexity": "复杂性",
        "fidelity": "忠实度",
    }
    print()
    print("=" * 62)
    print(f"  环境四维体检 · {len(tasks)} 个样本")
    print("=" * 62)

    for k in ("correctness", "diversity", "complexity", "fidelity"):
        v = dims[k]
        s = v.get("score")
        bar = "-" if s is None else ("#" * int(round(s * 20))).ljust(20, ".")
        num = "  n/a " if s is None else f"{s:.4f}"
        print(f"\n  {zh[k]}  {bar}  {num}")
        if s is None:
            print(f"      未测量：{v.get('note', '')}")
        else:
            if k == "diversity":
                det = v["detail"]
                print(f"      语义覆盖 {det['semantic']} · 类别均衡 {det['category']} "
                      f"· 结构离散 {det['structural']}")
                print(f"      类别数 {det['n_categories']} · {det['note']}")
                capc = v["category_cap"]
                print(f"      类别上限 {capc['cap']}：{'通过' if capc['ok'] else '触顶 ' + str(capc['violations'])}")
            elif k == "complexity":
                h = v["histogram"]
                print(f"      难度均值 {h['mean']} · 各档分布 "
                      + " ".join(f"{b['range'][0]}-{b['range'][1]}:{b['count']}" for b in h["bins"]))
            elif k == "fidelity":
                print(f"      类别分布距离 {v['category_js_distance']} · "
                      f"结构距离 {v['structural_distance']}")
            elif k == "correctness":
                b = v["blocked"]
                print(f"      废题率 {b['rate']}（{b['blocked']}/{b['n']}）")

    print(f"\n  综合判定：{report.verdict}")
    print("\n  类别分布：" + ", ".join(f"{k}={v}" for k, v in category_distribution(tasks).items()))

    if report["actions"]:
        print("\n  下一步：")
        for a in report["actions"]:
            print(f"    - {a}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
