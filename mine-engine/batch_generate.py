"""M3 批量生成：一条命令从健康体批量产出"差分验证通过"的审计样本。

流程（对齐清单 M3/M4/M5）：
  遍历 (健康合约 × 埋雷算子) 组合
    -> 算子生成埋雷版 + ground truth
    -> Foundry 差分验证（编译/ happy-path / PoC 差分）
    -> 通过则落盘 datasets/sample-XXXX/，失败记入 failures 并丢弃
  -> 写 datasets/index.jsonl（每行一个样本，便于切片/去重）
  -> 打印有效率与漏洞类型分布

确定性算子 + 固定 seed => 同参数重跑结果一致（可复现）。
新增算子后，只需在 registry 注册并在 COMBOS 加一行，即可线性扩充数据集。
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.generators import ContractGenerator
from engine.operators import default_registry
from engine.validators import FoundryDiffValidator


# (健康合约名, 健康源码相对 src/ 的路径, 漏洞类型, 默认难度 1-5)
COMBOS = [
    ("Vault", "Vault.sol", "reentrancy", 2),
    ("Ownable", "Ownable.sol", "access_control", 1),
]

SEED = 42


def resolve_forge() -> str:
    forge = shutil.which("forge")
    if forge:
        return forge
    candidate = Path.home() / ".foundry" / "forge.exe"
    if candidate.exists():
        return str(candidate)
    raise SystemExit("未找到 forge")


def _reset_datasets(ds: Path) -> None:
    """重建数据集目录：清空旧 sample-* 与 index.jsonl。"""
    if not ds.exists():
        ds.mkdir(parents=True)
        return
    for child in ds.iterdir():
        if child.name.startswith("sample-") or child.name == "index.jsonl":
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def main() -> None:
    forge = resolve_forge()
    registry = default_registry()
    generator = ContractGenerator(ROOT / "src")
    validator = FoundryDiffValidator(ROOT, forge_exe=forge)

    ds = ROOT / "datasets"
    _reset_datasets(ds)

    print("=" * 72)
    print(f"批量生成 · seed={SEED} · 组合数={len(COMBOS)}")
    print("=" * 72)

    # 1) 生成（加载健康体 -> 对应算子埋雷）
    raw = []
    for i, (contract, rel, vtype, difficulty) in enumerate(COMBOS):
        loaded = generator.run([{"contract_name": contract, "clean_rel_path": rel}])
        injector = registry.build_injector(vtype, seed=SEED, start_index=i)
        records = injector.run(loaded)
        for rec in records:
            rec["difficulty"] = difficulty
        raw.extend(records)

    # 2) 差分验证（逐样本临时覆盖黄金文件 -> forge test -> 恢复）
    validated = validator.run(raw)

    # 3) 通过则落盘；失败则丢弃并记录
    index_rows = []
    failures = []
    for rec in validated:
        issue = rec["issues"][0]
        if not rec["valid"]:
            failures.append({
                "sample_id": rec["sample_id"],
                "vuln_type": issue["vuln_type"],
                "reason": "forge 差分未通过（编译失败 / 破坏功能 / PoC 未差分）",
            })
            continue

        sample_dir = ds / rec["sample_id"]
        clean_dir = sample_dir / "clean"
        planted_dir = sample_dir / "planted"
        clean_dir.mkdir(parents=True, exist_ok=True)
        planted_dir.mkdir(parents=True, exist_ok=True)

        clean_name = f"{rec['contract_name']}.sol"
        planted_name = f"{rec['planted_contract_name']}.sol"
        (clean_dir / clean_name).write_text(rec["clean_source"], encoding="utf-8")
        (planted_dir / planted_name).write_text(rec["planted_source"], encoding="utf-8")
        (sample_dir / "meta.json").write_text(
            json.dumps(
                {
                    "sample_id": rec["sample_id"],
                    "clean": f"clean/{clean_name}",
                    "planted": f"planted/{planted_name}",
                    "ground_truth_types": [issue["vuln_type"]],
                    "issues": rec["issues"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        index_rows.append(
            {
                "sample_id": rec["sample_id"],
                "contract": rec["contract_name"],
                "vuln_type": issue["vuln_type"],
                "swc": issue["swc"],
                "severity": issue["severity"],
                "difficulty": rec.get("difficulty"),
                "clean": f"{rec['sample_id']}/clean/{clean_name}",
                "planted": f"{rec['sample_id']}/planted/{planted_name}",
                "validated": True,
                "golden_match": rec["matches_golden"],
            }
        )

    # 4) 写 index.jsonl
    index_path = ds / "index.jsonl"
    with index_path.open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 5) 报告
    total = len(validated)
    passed = len(index_rows)
    failed = len(failures)
    dist = Counter(r["vuln_type"] for r in index_rows)
    rate = (passed / total * 100) if total else 0.0

    print("\n[批量生成报告]")
    print(f"  组合/生成样本: {total}")
    print(f"  差分通过: {passed}    丢弃: {failed}    有效率: {rate:.1f}%")
    print("  漏洞类型分布: " + ", ".join(f"{k}={v}" for k, v in sorted(dist.items())))
    if failures:
        print("  失败明细:")
        for f in failures:
            print(f"    - {f['sample_id']} {f['vuln_type']}: {f['reason']}")
    print(f"  索引: {index_path.relative_to(ROOT)} ({passed} 行)")
    print("\n可复现：相同 seed 重跑，planted 源码与 index 完全一致。")
    print("=" * 72)


if __name__ == "__main__":
    main()
