"""E6 mini：C 类可验证性的核心检验 —— oracle 能否跨题复用。

对照实验设计
------------
A 类（CUA-Gym 式）：每题一个专属 reward function，成本随题数线性增长。
C 类（本文）：     一组领域 oracle 跨所有题复用，成本与题数无关。

本脚本量化：题数 N 增长时，两条路线的"判分器代码量"与"核验耗时"如何变化。
这是 C 类相对 A 类的唯一硬优势，必须有数字。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from vts.audit_core import (  # noqa: E402
    FRAUD_OPS, ORACLES, certify, make_seed_ledger,
)


def build(n_tasks: int, ops_per_task: int = 1):
    """生成 n_tasks 道题，每题随机选一个算子。"""
    trials = []
    for i in range(n_tasks):
        op = list(FRAUD_OPS)[i % len(FRAUD_OPS)]
        led = make_seed_ledger(i)
        trials.append((op, led))
    return trials


def oracle_code_lines() -> int:
    """统计 4 条 oracle 函数的实际代码行数（判分器代码量，与题数无关）。"""
    import inspect
    import vts.audit_core as core
    total = 0
    for fn in core.ORACLES.values():
        total += len(inspect.getsource(fn).splitlines())
    return total


def measure(n_tasks: int, repeats: int = 3) -> dict:
    """测 C 类路线的边际成本：核验 N 道题的耗时。"""
    trials = build(n_tasks)
    t0 = time.perf_counter()
    valid = 0
    for _ in range(repeats):
        for op, led in trials:
            d = certify(led, op, {}, "t")
            valid += 1 if d.valid else 0
    el = time.perf_counter() - t0
    return {
        "n_tasks": n_tasks,
        "n_oracles": len(ORACLES),
        "oracle_code_lines": oracle_code_lines(),
        "total_checks": len(trials) * repeats,
        "valid": valid,
        "valid_rate": round(valid / (len(trials) * repeats), 4),
        "elapsed_ms": round(el * 1000, 2),
        "per_task_ms": round(el / (len(trials) * repeats) * 1000, 4),
    }


def main() -> None:
    print("=" * 66)
    print("E6 mini：oracle 复用性 —— C 类可验证性的核心检验")
    print("=" * 66)

    print(f"\noracle 数量（领域先验，跨题复用）: {len(ORACLES)}")
    for n in ORACLES:
        print(f"  - {n}")
    print(f"舞弊算子数量: {len(FRAUD_OPS)}")

    print("\n--- 题数 N 增长时的边际成本 ---")
    print(f"{'N':>6} {'有效率':>8} {'总耗时ms':>10} {'每题ms':>10}")
    rows = []
    for n in [10, 50, 200, 1000]:
        r = measure(n)
        rows.append(r)
        print(f"{r['n_tasks']:>6} {r['valid_rate']:>8.4f} "
              f"{r['elapsed_ms']:>10.1f} {r['per_task_ms']:>10.4f}")

    # 关键论证：每题判分代码量恒为 0（oracle 不随题数增长）
    print("\n--- C 类 vs A 类 的成本结构对比 ---")
    print("A 类（CUA-Gym 式）：每题一个 LLM 派生的 reward function")
    print("  → N 题需要 N 份 reward 代码 + LLM 投票过滤（N 次调用）")
    print("C 类（本方案）：一组领域 oracle 跨题复用")
    print(f"  → N 题共用 {len(ORACLES)} 条 oracle，新增题目的边际代码量 = 0")

    total = sum(r["per_task_ms"] for r in rows) / len(rows)
    print(f"\n实测每题核验平均耗时: {total:.4f} ms")
    print(f"对应 1000 题: {total * 1000:.1f} ms（单次，无需 LLM 调用）")

    out = Path(__file__).parent / "results_e6_reuse.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n结果已写入 {out.name}")


if __name__ == "__main__":
    main()
