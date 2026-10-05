"""防伪检查（dummy check / oracle check）：每一道题都得先证明自己不是废题。

对齐行业术语（docs/11-fundamentals 2.3）：
  Terminal-Bench 用 `harbor run --agent oracle` 跑标准答案验证链路，
  官方 README 还要求 oracle 跑 5 次验题目稳定性。我们这里做的是同一件事。

查什么？三件事，任一件不过就判这道题不合格：

  1. 白卷（empty findings）——什么都不答
     普通题必须得 0 分。若 > 0，说明这道题"不答也给分"，是废题
     （典型原因：判分逻辑写错，或题干里直接写了答案）
  2. 标准答案（golden，由注入漏洞时的 ground truth 自动构造）
     必须拿满分。若拿不到，说明判分器或标注有问题——
     这是最容易被忽略的一类 bug，它不会报错，只会让所有分数悄悄偏低
  3. 反向白卷（chaff 题专用：故意乱报一个漏洞）
     必须得 0 分。若 > 0，说明"瞎报也有分"，chaff就白设了

⚠️ chaff 题的判据是**反过来的**：
   chaff 题里没有雷，"什么都不报"才是正确答案，所以白卷必须**满分**、乱报必须**0 分**。
   （上一版方案在这里写反了，实测跑一遍才发现。见 docs/10-action-plan 第 8 章）

用法：
    py run_dummy_check.py                 # 检查全部样本
    py run_dummy_check.py --scorer v2     # 用 v2 判分器（默认 v2）
    py run_dummy_check.py --json          # 机器可读输出
退出码：0=全部通过，1=有不合格题目（可接 CI）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.scorers.report_score import score_report, score_report_v2  # noqa: E402

EPS = 1e-6
PASS, FAIL = "✅", "❌"


def load_samples(ds: Path) -> list:
    return [
        json.loads(line)
        for line in (ds / "index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_gt(ds: Path, sample_id: str) -> list:
    meta = json.loads((ds / sample_id / "meta.json").read_text(encoding="utf-8"))
    return meta.get("issues", []) or []


def golden_findings(gt: list) -> list:
    """把 ground truth 标注翻译成模型该输出的 findings 格式。

    ground truth 是注入漏洞时自动生成的（含函数级行区间），
    这里取区间起点作为 line——判分器遵循"判分严格度不超过标注粒度"，
    所以报区间内任意一行都算命中。
    """
    out = []
    for g in gt:
        loc = g.get("location") or {}
        out.append({
            "vuln_type": g.get("vuln_type", ""),
            "function": loc.get("function", "") or g.get("function", ""),
            "line": loc.get("start_line", 0) or g.get("line", 0),
            "severity": g.get("severity", ""),
            "evidence": "ground truth（由注入算子自动生成）",
        })
    return out


def decoy_finding() -> list:
    """反向白卷：一个明显错误的发现，用来验证"瞎报会被惩罚"。"""
    return [{
        "vuln_type": "reentrancy",
        "function": "totally_made_up_function",
        "line": 1,
        "severity": "low",
        "evidence": "随便报的，应该被判为误报",
    }]


def fmt(v) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="防伪检查：白卷 / 标准答案 / 反向白卷")
    ap.add_argument("--scorer", default="v2", choices=["v1", "v2"],
                    help="v1=类型+函数匹配；v2=类型+定位IoU+严重度加权（默认 v2）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非表格")
    ap.add_argument("--only", default="", help="逗号分隔的 sample_id，默认全部")
    args = ap.parse_args()

    score_fn = score_report_v2 if args.scorer == "v2" else score_report
    ds = ROOT / "datasets"
    samples = load_samples(ds)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        samples = [s for s in samples if s["sample_id"] in wanted]

    rows, bad = [], []
    for s in samples:
        sid = s["sample_id"]
        gt = load_gt(ds, sid)
        is_decoy = (s.get("vuln_type") == "decoy") or (not gt)

        # 三项检查
        empty = score_fn(gt, [])
        golden = score_fn(gt, golden_findings(gt))
        reverse = score_fn(gt, decoy_finding())

        # 每项：(名称, 是否通过, 实测值, 是否作为硬性判据)
        if is_decoy:
            # chaff 题判据相反：白卷=满分（没乱报）、乱报=0 分
            checks = [
                ("白卷应满分(没乱报)", empty["f1"] >= 1 - EPS, empty["f1"], True),
                ("乱报应0分", reverse["f1"] <= EPS, reverse["f1"], True),
                ("标准答案应满分", golden["f1"] >= 1 - EPS, golden["f1"], True),
            ]
        else:
            checks = [
                ("白卷应0分", empty["f1"] <= EPS, empty["f1"], True),
                ("标准答案应满分", golden["f1"] >= 1 - EPS, golden["f1"], True),
                # 普通题上"乱报"不作硬性判据：类型若碰巧说对、只是定位错，
                # 判分器给部分分是合理行为，不该判题目不合格。这里只记录，供观察。
                ("乱报(仅记录)", True, reverse["f1"], False),
            ]

        ok = all(passed for _, passed, _, binding in checks if binding)

        rows.append({
            "sample_id": sid,
            "kind": "chaff" if is_decoy else "普通",
            "n_gt": len(gt),
            "empty_f1": round(empty["f1"], 4),
            "golden_f1": round(golden["f1"], 4),
            "reverse_f1": round(reverse["f1"], 4),
            "ok": ok,
            "checks": [{"name": n, "ok": p, "value": round(v, 4), "binding": b}
                       for n, p, v, b in checks],
        })
        if not ok:
            bad.append(sid)

    if args.json:
        print(json.dumps({"scorer": args.scorer, "rows": rows, "failed": bad},
                         ensure_ascii=False, indent=2))
        return 1 if bad else 0

    print("=" * 92)
    print(f"防伪检查（dummy / oracle check）· scorer={args.scorer} · 样本 {len(samples)} 个")
    print("=" * 92)
    print(f"{'sample':<18} {'类型':<6} {'雷数':>4} {'白卷':>7} {'标准答案':>9} {'乱报':>7}  判定")
    print("-" * 92)
    for r in rows:
        print(f"{r['sample_id']:<18} {r['kind']:<6} {r['n_gt']:>4} "
              f"{fmt(r['empty_f1']):>7} {fmt(r['golden_f1']):>9} {fmt(r['reverse_f1']):>7}  "
              f"{PASS if r['ok'] else FAIL}")
    print("=" * 92)

    n_decoy = sum(1 for r in rows if r["kind"] == "chaff")
    print(f"chaff 题 {n_decoy} 个 · 普通题 {len(rows) - n_decoy} 个")

    if bad:
        print(f"\n❌ {len(bad)} 道题不合格，必须从数据集里踢出去：{', '.join(bad)}")
        for r in rows:
            if r["ok"]:
                continue
            print(f"\n  {r['sample_id']}（{r['kind']}）")
            for c in r["checks"]:
                print(f"    {'✅' if c['ok'] else '❌'} {c['name']}：实测 {c['value']}")
        return 1

    print("\n✅ 全部题目通过防伪检查")
    if n_decoy <= 1:
        print("⚠️  但 chaff 题只有 1 道：测不了误报率的审计评测是瘸腿的。"
              "建议至少补到 3–5 道（见 docs/10-action-plan 3.2）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
