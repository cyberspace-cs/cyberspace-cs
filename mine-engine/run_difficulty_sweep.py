"""第四步验证脚本：扫描难度刻度 0..5，产出"难度 -> 结构指标 / AI 分数"曲线。

离线（无 LLM / 无 forge）也能跑：只输出结构指标（诱饵数、是否伪装、是否跨函数），
证明旋钮确实改变了题目的"长相"。配了 LLM_API_KEY 时，会对每档跑一次审计并算 F1，
得到真正的难度-分数曲线（注意 repeat=1 仅供参考）。

用法：
  python run_difficulty_sweep.py --sample sample-0001
  python run_difficulty_sweep.py --sample sample-0001 --out sweep.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.operators.difficulty import PRESETS, apply_difficulty  # noqa: E402


def load_sample(ds: Path, sample_id: str):
    planted_dir = ds / sample_id / "planted"
    if not planted_dir.exists():
        raise SystemExit(f"找不到样本 {sample_id}（{planted_dir} 不存在）")
    sol_files = list(planted_dir.glob("*.sol"))
    if not sol_files:
        raise SystemExit(f"{planted_dir} 下没有 .sol")
    planted_source = sol_files[0].read_text(encoding="utf-8")
    meta = json.loads((ds / sample_id / "meta.json").read_text(encoding="utf-8"))
    return planted_source, meta


def run_audit(planted_source: str, meta: dict, score_fn):
    """只有显式 --audit 才跑（会真调 LLM、花钱）；否则返回 None。"""
    from engine.llm.env import load_dotenv  # noqa: E402
    from engine.llm import LLMClient  # noqa: E402
    from engine.agents import AuditAgent  # noqa: E402

    load_dotenv(ROOT)
    if not __import__("os").environ.get("LLM_API_KEY"):
        return None
    client = LLMClient()
    agent = AuditAgent(client, strategy="standard")
    report = agent.audit(planted_source)
    findings = report.get("findings", [])
    sc = score_fn(meta.get("issues", []), findings)
    return sc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="sample-0001")
    ap.add_argument("--out", default="results_difficulty_sweep.json")
    ap.add_argument("--scorer", choices=["v1", "v2"], default="v2")
    ap.add_argument("--audit", action="store_true",
                    help="真跑 LLM 审计并算 F1（默认只出结构指标，不花钱）")
    args = ap.parse_args()

    from engine.scorers.report_score import score_report, score_report_v2  # noqa: E402

    score_fn = score_report_v2 if args.scorer == "v2" else score_report
    ds = ROOT / "datasets"
    planted_source, meta = load_sample(ds, args.sample)
    gt = meta.get("issues", [])

    print("=" * 78)
    print(f"难度扫描 · 样本 {args.sample} · 刻度 0..5")
    print("=" * 78)
    print(f"{'刻度':<4} {'诱饵':<4} {'伪装':<5} {'跨函数':<6} {'改写k':<6} {'F1':<7} 说明")
    print("-" * 78)

    rows = []
    for level in range(0, 6):
        knob = PRESETS[level]
        new_src, metrics = apply_difficulty(planted_source, knob)
        sc = run_audit(new_src, meta, score_fn) if args.audit else None
        f1 = f"{sc['f1']:.3f}" if sc else "n/a"
        note = []
        if metrics["decoy_count"]:
            note.append(f"+{metrics['decoy_count']}诱饵")
        if metrics["obfuscated"]:
            note.append("伪装")
        if metrics["cross_function"]:
            note.append("跨函数")
        if knob.variation_k:
            note.append(f"改写x{knob.variation_k}")
        print(
            f"{level:<4} {metrics['decoy_count']:<4} "
            f"{('Y' if metrics['obfuscated'] else '-'):<5} "
            f"{('Y' if metrics['cross_function'] else '-'):<6} "
            f"{knob.variation_k:<6} {f1:<7} {' '.join(note) or '原样'}"
        )
        rows.append({"level": level, "metrics": metrics, "f1": sc["f1"] if sc else None})

    with (ROOT / args.out).open("w", encoding="utf-8") as fh:
        json.dump(
            {"sample": args.sample, "rows": rows, "ground_truth": gt},
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print("-" * 78)
    print(f"结果已落盘 {args.out}（F1 为 n/a 表示本机未配 LLM，仅结构指标）")
    print("验收（见 10-action-plan 3.4）：刻度↑时诱饵/伪装/跨函数应单调增加；")
    print("配 LLM 后 F1 应总体下降（曲线单调），且不同 seed 排名一致（曲线稳定）。")


if __name__ == "__main__":
    main()
