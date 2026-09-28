"""一键演示埋雷引擎闭环（M0 + M1）。

运行：
    py run_demo.py
流程：
    1) 加载健康 Vault；
    2) 重入算子自动生成埋雷版 VaultPlanted 与 ground truth；
    3) 样本落盘到 datasets/sample-0001/；
    4) Foundry 差分验证（算子输出等价黄金版，且 forge test 全绿）；
    5) 对三份审计报告打分，展示 precision 同时计分如何防“全报一遍”。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.core import Pipeline
from engine.generators import ContractGenerator
from engine.operators import ReentrancyInjector
from engine.scorers import AuditReportScorer
from engine.validators import FoundryDiffValidator


def resolve_forge() -> str:
    forge = shutil.which("forge")
    if forge:
        return forge
    candidate = Path.home() / ".foundry" / "forge.exe"
    if candidate.exists():
        return str(candidate)
    raise SystemExit("未找到 forge，请确认 Foundry 已安装并在 PATH 中")


# 审计题面里可选的漏洞类型全集（用于演示“全报一遍”的作弊报告）
ALL_VULN_TYPES = [
    "reentrancy", "integer_overflow", "integer_underflow", "tx_origin",
    "unchecked_call", "delegatecall_injection", "access_control",
    "flash_loan", "front_running", "signature_replay",
    "arbitrary_jump", "denial",
]


def main() -> None:
    forge = resolve_forge()
    print("=" * 72)
    print("埋雷引擎 mine-engine · 闭环演示")
    print("=" * 72)

    # 1) + 2) 生成健康体 -> 埋雷
    gen_pipeline = Pipeline(
        [
            ContractGenerator(ROOT / "src"),
            ReentrancyInjector(seed=42),
        ],
        name="generate-and-plant",
    )
    seeds = [{"contract_name": "Vault", "clean_rel_path": "Vault.sol"}]
    samples = gen_pipeline.run(seeds)
    sample = samples[0]
    print(f"\n[1] 已加载健康合约：{sample['clean_path']}")
    print(f"[2] 已埋雷：{sample['sample_id']}  合约 {sample['contract_name']}"
          f" -> {sample['planted_contract_name']}")

    # 3) 样本落盘
    sample_dir = ROOT / "datasets" / sample["sample_id"]
    clean_dir = sample_dir / "clean"
    planted_dir = sample_dir / "planted"
    clean_dir.mkdir(parents=True, exist_ok=True)
    planted_dir.mkdir(parents=True, exist_ok=True)

    (clean_dir / "Vault.sol").write_text(sample["clean_source"], encoding="utf-8")
    (planted_dir / "VaultPlanted.sol").write_text(
        sample["planted_source"], encoding="utf-8"
    )
    meta = {
        "sample_id": sample["sample_id"],
        "clean": "clean/Vault.sol",
        "planted": "planted/VaultPlanted.sol",
        "ground_truth_types": ["reentrancy"],
        "issues": sample["issues"],
    }
    (sample_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[3] 样本已落盘：{sample_dir}")

    # 4) Foundry 差分验证
    validator = FoundryDiffValidator(ROOT, forge_exe=forge)
    validated = validator.run([sample])
    sample = validated[0]

    print(f"[4] 差分验证：算子输出等价黄金版 = {sample['matches_golden']}；"
          f"forge test 全绿 = {sample['valid']}")
    print("    --- forge test 摘要 ---")
    for line in sample["validation_log"].splitlines():
        if "[PASS]" in line or "[FAIL]" in line or "Suite result" in line:
            print("    " + line.strip())

    # 5) 报告判分（同一 ground truth，三种报告策略）
    report_records = [
        {"report": "A 作弊：把所有类型全报一遍",
         "ground_truth_types": ["reentrancy"], "predicted_types": ALL_VULN_TYPES},
        {"report": "B 好审计：只报确实发现的重入",
         "ground_truth_types": ["reentrancy"], "predicted_types": ["reentrancy"]},
        {"report": "C 漏报：什么都没发现",
         "ground_truth_types": ["reentrancy"], "predicted_types": []},
    ]
    scored = AuditReportScorer().run(report_records)

    print("\n[5] 审计报告判分（ground truth = reentrancy）")
    header = f"    {'报告':<28}{'recall':>8}{'precision':>11}{'f1':>8}"
    print(header)
    for rec in scored:
        s = rec["scores"]
        print(f"    {rec['report']:<26}{s['recall']:>8}{s['precision']:>11}{s['f1']:>8}")
    print("\n结论：只看 recall，作弊报告 A 与好审计 B 都满分；")
    print("      加入 precision 后，A 被误报拖垮，B 才是真本事。")

    print("\n" + "=" * 72)
    print("闭环完成。")
    print("=" * 72)


if __name__ == "__main__":
    main()
