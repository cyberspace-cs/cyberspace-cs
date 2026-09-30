"""Level 3 baseline：给 4 模型看 LendingPoolPlanted 多文件仓库，输出审计报告，四维打分。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.llm.client import LLMClient
from engine.agents.level3_agent import Level3AuditAgent
from engine.scorers.level3_score import score_level3, GROUND_TRUTH

BASE = "https://api.deepseek.com/v1"
KEY = os.environ["LLM_API_KEY"]  # 从环境变量读

MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
]


def load_files() -> dict[str, str]:
    return {
        "LendingPoolPlanted.sol": (ROOT / "src/planted/LendingPoolPlanted.sol").read_text(encoding="utf-8"),
        "Ownable.sol": (ROOT / "src/Ownable.sol").read_text(encoding="utf-8"),
    }


def main():
    files = load_files()
    results = {}
    for model in MODELS:
        print(f"\n=== {model} ===", flush=True)
        client = LLMClient(base_url=BASE, api_key=KEY, model=model, timeout=180)
        agent = Level3AuditAgent(client)
        t0 = time.time()
        try:
            out = agent.audit_repo(files)
            dt = time.time() - t0
            score = score_level3(out["findings"])
            results[model] = {"score": score, "findings": out["findings"], "sec": round(dt, 1)}
            print(f"  findings={len(out['findings'])} score={score}", flush=True)
            for f in out["findings"]:
                print(f"    - {f.get('vuln_type','?'):20s} {f.get('contract','?')}.{f.get('function','?')} sev={f.get('severity','?')}", flush=True)
        except Exception as e:
            results[model] = {"error": str(e)}
            print(f"  ERROR: {e}", flush=True)

    out_path = ROOT / "results_level3.json"
    out_path.write_text(json.dumps({"ground_truth": GROUND_TRUTH, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
