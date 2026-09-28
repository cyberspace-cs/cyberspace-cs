"""一键演示埋雷引擎闭环（M2：两个算子，经算子注册中心编排）。

运行：
    py run_demo.py
流程：
    1) 经注册中心，对健康 Vault / Ownable 分别埋入重入、访问控制缺失；
    2) 样本落盘到 datasets/sample-000X（clean/planted/meta.json）；
    3) Foundry 差分验证（算子输出等价黄金版，且 forge test 全绿）；
    4) 对审计报告打分，展示 precision 同时计分如何防“全报一遍”。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.generators import ContractGenerator
from engine.operators import default_registry
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


# (健康合约, 源文件相对路径, 要埋的漏洞类型)
PLAN = [
    {"contract_name": "Vault", "clean_rel_path": "Vault.sol", "vuln_type": "reentrancy"},
    {"contract_name": "Ownable", "clean_rel_path": "Ownable.sol", "vuln_type": "access_control"},
]

# 审计题面里可选的漏洞类型全集（用于演示“全报一遍”的作弊报告）
ALL_VULN_TYPES = [
    "reentrancy", "integer_overflow", "integer_underflow", "tx_origin",
    "unchecked_call", "delegatecall_injection", "access_control",
    "flash_loan", "front_running", "signature_replay",
    "arbitrary_jump", "denial",
]


def main() -> None:
    forge = resolve_forge()
    registry = default_registry()
    generator = ContractGenerator(ROOT / "src")
    validator = FoundryDiffValidator(ROOT, forge_exe=forge)

    print("=" * 72)
    print("埋雷引擎 mine-engine · 闭环演示（算子注册中心 / 2 个算子）")
    print("=" * 72)
    print("已注册算子:", ", ".join(registry.types()))

    # 1) 加载健康体 -> 经注册中心取对应算子埋雷
    samples = []
    for i, spec in enumerate(PLAN):
        loaded = generator.run(
            [{"contract_name": spec["contract_name"],
              "clean_rel_path": spec["clean_rel_path"]}]
        )
        injector = registry.build_injector(spec["vuln_type"], seed=42, start_index=i)
        samples.extend(injector.run(loaded))

    # 2) 样本落盘
    for rec in samples:
        sample_dir = ROOT / "datasets" / rec["sample_id"]
        clean_dir = sample_dir / "clean"
        planted_dir = sample_dir / "planted"
        clean_dir.mkdir(parents=True, exist_ok=True)
        planted_dir.mkdir(parents=True, exist_ok=True)

        (clean_dir / f"{rec['contract_name']}.sol").write_text(
            rec["clean_source"], encoding="utf-8"
        )
        (planted_dir / f"{rec['planted_contract_name']}.sol").write_text(
            rec["planted_source"], encoding="utf-8"
        )
        meta = {
            "sample_id": rec["sample_id"],
            "clean": f"clean/{rec['contract_name']}.sol",
            "planted": f"planted/{rec['planted_contract_name']}.sol",
            "ground_truth_types": [rec["issues"][0]["vuln_type"]],
            "issues": rec["issues"],
        }
        (sample_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 3) Foundry 差分验证
    validated = validator.run(samples)

    print("\n[差分验证]")
    for rec in validated:
        print(
            f"  {rec['sample_id']}  {rec['issues'][0]['vuln_type']:<15}"
            f"等价黄金版={rec['matches_golden']}  forge 全绿={rec['valid']}"
        )

    print("\n  --- 最后一次 forge test 摘要 ---")
    last_log = validated[-1]["validation_log"]
    for line in last_log.splitlines():
        if "[PASS]" in line or "[FAIL]" in line or "Suite result" in line:
            print("  " + line.strip())

    # 4) 报告判分（同一 ground truth = reentrancy，三种报告策略）
    report_records = [
        {"report": "A 作弊：把所有类型全报一遍",
         "ground_truth_types": ["reentrancy"], "predicted_types": ALL_VULN_TYPES},
        {"report": "B 好审计：只报确实发现的重入",
         "ground_truth_types": ["reentrancy"], "predicted_types": ["reentrancy"]},
        {"report": "C 漏报：什么都没发现",
         "ground_truth_types": ["reentrancy"], "predicted_types": []},
    ]
    scored = AuditReportScorer().run(report_records)

    print("\n[审计报告判分] ground truth = reentrancy")
    print(f"  {'报告':<28}{'recall':>8}{'precision':>11}{'f1':>8}")
    for rec in scored:
        s = rec["scores"]
        print(f"  {rec['report']:<26}{s['recall']:>8}{s['precision']:>11}{s['f1']:>8}")
    print("\n结论：只看 recall，A 与 B 都满分；加入 precision 后，A 被误报拖垮。")

    print("\n" + "=" * 72)
    print("闭环完成。")
    print("=" * 72)


if __name__ == "__main__":
    main()
