"""AI Filter（HLE adversarial filtering 思路）：筛掉"太容易"的题。

做法：对每道已落盘的样本，用一组"筛选模型"（默认便宜的 flash 级）各做一遍审计；
  - 如果所有筛选模型都全对（真雷找全 + 零误报 + 诱饵没乱报）→ 标记 trivial（太易，SOTA 一眼看穿）
  - 如果至少一个筛选模型漏报/误报 → 标记 differentiating（有区分度，保留进正式 benchmark）

不删除样本，只打标签写回 index.jsonl，并打印统计。下一步对 trivial 题加难（组合雷/干扰/Exploit）。

用法：
    $env:LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    $env:LLM_API_KEY="sk-..."
    $env:FILTER_MODELS="qwen3.8-flash,deepseek-v4-flash"   # 筛选用的便宜模型
    py run_ai_filter.py
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
    filter_models = [
        m.strip()
        for m in os.environ.get("FILTER_MODELS", "qwen3.8-flash,deepseek-v4-flash").split(",")
        if m.strip()
    ]

    ds = ROOT / "datasets"
    index_path = ds / "index.jsonl"
    index = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    print("=" * 72)
    print(f"AI Filter · 样本 {len(index)} · 筛选模型 {filter_models}")
    print("=" * 72)

    trivial, differentiating = [], []
    for s in index:
        planted = (ds / s["planted"]).read_text(encoding="utf-8")
        gt = load_ground_truth(ds / s["sample_id"])
        n_gt = len(gt)

        model_scores = {}
        for fm in filter_models:
            client = LLMClient(base_url=base_url, api_key=api_key, model=fm, temperature=0.0)
            agent = AuditAgent(client, strategy="standard")
            report = agent.audit(planted)
            sc = score_report(gt, report["findings"])
            model_scores[fm] = sc

        # 全对判定：真雷找全(tp==n_gt, fn==0) 且 零误报(fp==0)
        all_correct = all(
            sc["tp"] == n_gt and sc["fp"] == 0 and sc["fn"] == 0
            for sc in model_scores.values()
        )
        label = "trivial" if all_correct else "differentiating"
        s["ai_filter"] = label
        s["filter_scores"] = {
            fm: {"tp": sc["tp"], "fp": sc["fp"], "fn": sc["fn"]}
            for fm, sc in model_scores.items()
        }

        per = "  ".join(
            f"{fm}:tp={sc['tp']}/fp={sc['fp']}/fn={sc['fn']}"
            for fm, sc in model_scores.items()
        )
        tag = "太易" if label == "trivial" else "有区分度"
        print(f"  {s['sample_id']:<18} gt={s['vuln_type']:<15} [{tag}]  {per}")

        (trivial if label == "trivial" else differentiating).append(s["sample_id"])

    # 写回 index.jsonl（去掉临时 filter_scores 不进正式索引？保留，便于复现）
    with index_path.open("w", encoding="utf-8") as fh:
        for s in index:
            out = {k: v for k, v in s.items()}
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")

    print("\n" + "=" * 72)
    print(f"太易(trivial, 筛选模型全对): {len(trivial)} -> {trivial}")
    print(f"有区分度(differentiating):  {len(differentiating)} -> {differentiating}")
    if trivial:
        print("下一步：对 trivial 题加难（组合雷/干扰代码/Exploit PoC 模式）。")
    print("=" * 72)


if __name__ == "__main__":
    main()
