"""Level 3 baseline：给模型看 StakingVaultPlanted 多文件仓库，输出审计报告，四维打分（带 Gate）。

Gate 流程：
1. Gate 1: JSON 解析（不过 → 0 分）
2. 对每个 finding 跑 Gate 2+3: PoC 编译 + test
3. 四维评分（利用分用 gate 结果）
"""

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
from engine.gates.gate_json import gate_json_parse
from engine.gates.gate_poc import gate_poc_for_finding
from engine.llm import load_dotenv

load_dotenv()  # 让 .env 里的密钥在下面这行读取之前就位

BASE = "https://api.deepseek.com/v1"
KEY = os.environ["LLM_API_KEY"]

MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
]


def load_files() -> dict[str, str]:
    return {
        "StakingVaultPlanted.sol": (ROOT / "src/planted/StakingVaultPlanted.sol").read_text(encoding="utf-8"),
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
            raw = agent.audit_repo_raw(files)
            dt = time.time() - t0

            # Gate 1: JSON parse
            ok, data, reason = gate_json_parse(raw)
            if not ok:
                results[model] = {"gate1_pass": False, "gate1_reason": reason, "total": 0.0}
                print(f"  Gate1 FAIL: {reason}", flush=True)
                continue

            findings = data.get("findings", [])
            print(f"  Gate1 OK, findings={len(findings)}", flush=True)

            # Gate 2+3: 每个 finding 的 PoC
            poc_gates = {}
            for i, f in enumerate(findings):
                gate = gate_poc_for_finding(f, files)
                poc_gates[i] = gate
                status = "PASS" if gate.get("test_passed") else ("COMPILE_FAIL" if not gate.get("compile_passed") else "TEST_FAIL")
                print(f"    finding[{i}] {f.get('vuln_type','?'):20s} poc_gate={status}", flush=True)

            # 四维评分
            score = score_level3(findings, poc_gate_results=poc_gates)
            score["gate1_pass"] = True
            results[model] = {"score": score, "findings": findings, "poc_gates": poc_gates, "sec": round(dt, 1)}
            print(f"  score={score}", flush=True)

        except Exception as e:
            results[model] = {"error": str(e)}
            print(f"  ERROR: {e}", flush=True)

    out_path = ROOT / "results_level3.json"
    out_path.write_text(
        json.dumps({"ground_truth": GROUND_TRUTH, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nsaved -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
