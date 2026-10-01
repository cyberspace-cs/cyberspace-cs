"""M6/M7 审计 benchmark：对 datasets/index.jsonl 里的每个样本，跑审计 Agent，按 ground truth 判分。

用法（密钥走环境变量，绝不写入仓库）：
    $env:LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    $env:LLM_API_KEY="sk-..."
    $env:LLM_MODELS="qwen3.8-flash,deepseek-v4-flash,qwen3.8-max"
    py run_benchmark.py

M7 新增：
    py run_benchmark.py --repeat 5          # 每个 (模型,样本) 跑 5 次，输出 mean±std
    py run_benchmark.py --scorer v2         # 用 v2 打分（类型+定位IoU+严重度加权）
    py run_benchmark.py --out results.json  # 结果落盘，供难度/IRT 分析复用

为什么需要 --repeat：LLM 单次采样有随机性（README M6 已观察到"上次翻车这次满分"），
单次结果不构成结论。多次运行才能给出 mean ± std，才能谈差距是否显著。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.agents import AuditAgent  # noqa: E402
from engine.llm import LLMClient  # noqa: E402
from engine.scorers.report_score import score_report, score_report_v2  # noqa: E402


def load_ground_truth(sample_dir: Path) -> list:
    meta = json.loads((sample_dir / "meta.json").read_text(encoding="utf-8"))
    return meta.get("issues", [])


def main() -> int:
    ap = argparse.ArgumentParser(description="审计 benchmark")
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个 (模型,样本) 重复次数，默认 1；建议 >=5 以获得稳定结论")
    ap.add_argument("--scorer", default="v1", choices=["v1", "v2"],
                    help="v1=类型+函数匹配；v2=类型+定位IoU+严重度加权（默认 v1）")
    ap.add_argument("--only", default="", help="逗号分隔的 sample_id，默认全部")
    ap.add_argument("--out", default="", help="结果 JSON 落盘路径")
    args = ap.parse_args()

    base_url = os.environ["LLM_BASE_URL"]
    api_key = os.environ["LLM_API_KEY"]
    models = [m.strip() for m in os.environ.get("LLM_MODELS", "qwen3.8-flash").split(",") if m.strip()]
    strategy = os.environ.get("LLM_PROMPT", "standard")
    score_fn = score_report_v2 if args.scorer == "v2" else score_report

    ds = ROOT / "datasets"
    index = [
        json.loads(line)
        for line in (ds / "index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        index = [r for r in index if r["sample_id"] in wanted]

    print("=" * 78)
    print(f"审计 benchmark · 样本 {len(index)} 个 · 模型 {len(models)} 个 · "
          f"prompt={strategy} · scorer={args.scorer} · repeat={args.repeat}")
    print("=" * 78)

    summary, all_runs = [], {}
    for model in models:
        client = LLMClient(base_url=base_url, api_key=api_key, model=model, temperature=0.0)
        agent = AuditAgent(client, strategy=strategy)
        per_sample = {}

        for s in index:
            planted = (ds / s["planted"]).read_text(encoding="utf-8")
            gt = load_ground_truth(ds / s["sample_id"])

            f1s, recs, precs = [], [], []
            last = {"tp": 0, "fp": 0, "fn": 0}
            for _ in range(max(1, args.repeat)):
                report = agent.audit(planted)
                sc = score_fn(gt, report["findings"])
                last = sc
                f1s.append(sc["f1"])
                recs.append(sc["recall"])
                precs.append(sc["precision"])

            per_sample[s["sample_id"]] = {
                "vuln_type": s["vuln_type"],
                "f1_mean": round(statistics.fmean(f1s), 4),
                "f1_std": round(statistics.pstdev(f1s), 4) if len(f1s) > 1 else 0.0,
                "recall_mean": round(statistics.fmean(recs), 4),
                "precision_mean": round(statistics.fmean(precs), 4),
                "runs": len(f1s),
            }
            std_note = f" ±{per_sample[s['sample_id']]['f1_std']:.3f}" if len(f1s) > 1 else ""
            print(f"  [{model}] {s['sample_id']} gt={s['vuln_type']:<15} "
                  f"tp={last['tp']} fp={last['fp']} fn={last['fn']} "
                  f"R={last['recall']:.3f} P={last['precision']:.3f} "
                  f"F1={per_sample[s['sample_id']]['f1_mean']:.3f}{std_note}")

        # 全样本汇总（按样本平均，避免长样本主导）
        if per_sample:
            m_f1 = statistics.fmean(v["f1_mean"] for v in per_sample.values())
            m_r = statistics.fmean(v["recall_mean"] for v in per_sample.values())
            m_p = statistics.fmean(v["precision_mean"] for v in per_sample.values())
            m_std = statistics.fmean(v["f1_std"] for v in per_sample.values())
        else:
            m_f1 = m_r = m_p = m_std = 0.0
        summary.append((model, m_r, m_p, m_f1, m_std))
        all_runs[model] = per_sample

    print("\n" + "=" * 78)
    print(f"{'model':<28} {'Recall':>8} {'Prec':>8} {'F1':>8} {'F1 std':>9}")
    print("-" * 78)
    for model, r, p, f1, std in summary:
        print(f"{model:<28} {r:>8.3f} {p:>8.3f} {f1:>8.3f} {std:>9.3f}")
    print("=" * 78)
    if args.repeat == 1:
        print("提示：当前为单次采样，结论不稳定。建议加 --repeat 5 再对比模型。")

    if args.out:
        out_path = ROOT / args.out
        out_path.write_text(
            json.dumps({"scorer": args.scorer, "repeat": args.repeat, "results": all_runs},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
