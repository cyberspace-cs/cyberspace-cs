"""M6 审计 benchmark：对 datasets/index.jsonl 里的每个样本，跑审计 Agent，按 ground truth 判分。

用法（密钥走环境变量，绝不写入仓库）：
    $env:LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    $env:LLM_API_KEY="sk-..."
    $env:LLM_MODELS="qwen3.8-flash,deepseek-v4-flash,qwen3.8-max"
    py run_benchmark.py

输出每个模型在全部样本上的 recall / precision / F1 汇总表 + 每样本明细。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.agents import AuditAgent
from engine.llm import LLMClient
from engine.scorers.report_score import score_report


def load_ground_truth(sample_dir: Path) -> list:
    meta = json.loads((sample_dir / "meta.json").read_text(encoding="utf-8"))
    return meta.get("issues", [])


def main() -> None:
    base_url = os.environ["LLM_BASE_URL"]
    api_key = os.environ["LLM_API_KEY"]
    models = [m.strip() for m in os.environ.get("LLM_MODELS", "qwen3.8-flash").split(",") if m.strip()]
    strategy = os.environ.get("LLM_PROMPT", "standard")

    ds = ROOT / "datasets"
    index = [
        json.loads(line)
        for line in (ds / "index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    print("=" * 72)
    print(f"审计 benchmark · 样本 {len(index)} 个 · 模型 {len(models)} 个 · prompt策略={strategy}")
    print("=" * 72)

    summary = []
    for model in models:
        client = LLMClient(base_url=base_url, api_key=api_key, model=model, temperature=0.0)
        agent = AuditAgent(client, strategy=strategy)
        tot = {"tp": 0, "fp": 0, "fn": 0}
        detail = []
        for s in index:
            planted = (ds / s["planted"]).read_text(encoding="utf-8")
            gt = load_ground_truth(ds / s["sample_id"])
            report = agent.audit(planted)
            sc = score_report(gt, report["findings"])
            for k in ("tp", "fp", "fn"):
                tot[k] += sc[k]
            detail.append((s["sample_id"], s["vuln_type"], sc))
            print(f"  [{model}] {s['sample_id']} gt={s['vuln_type']:<15} "
                  f"tp={sc['tp']} fp={sc['fp']} fn={sc['fn']} "
                  f"R={sc['recall']} P={sc['precision']} F1={sc['f1']}")

        tp, fp, fn = tot["tp"], tot["fp"], tot["fn"]
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        summary.append((model, tp, fp, fn, recall, precision, f1))

    print("\n" + "=" * 72)
    print(f"{'model':<28} {'TP':>3} {'FP':>3} {'FN':>3} {'Recall':>7} {'Prec':>7} {'F1':>7}")
    print("-" * 72)
    for model, tp, fp, fn, r, p, f1 in summary:
        print(f"{model:<28} {tp:>3} {fp:>3} {fn:>3} {r:>7.3f} {p:>7.3f} {f1:>7.3f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
