"""F4 验收：参照 oracle 是否具备"按审计认定分层"的分辨力。

为什么需要这个脚本
------------------
`28-A0前置诊断与方案迭代v5.md` 实测发现：四个注入算子分属四条不同审计认定，
但违反的 oracle 集合**完全相同**，4 条 oracle 中 2 条**从未被任何算子触发**
⇒ 参照层只提供一个比特的信息，"四档难度"被压平成一档。

若直接跑 A0（$8–12），会买到一个"看着像曲线、其实是一个点"的结果。
本脚本是 A0 的**准入闸门**：不通过就不该投钱。

三项验收
--------
1. **零误报**：干净账套（150 seed × 4 期 = 600 个样本）不得触发任何 oracle。
   —— 参照层对"没问题"的账套报警，是不可用的。
2. **签名分离**：四个主算子的违反签名必须**两两不同**（否则难度不可区分）。
3. **可区分性**：任意两主算子的签名差集非空（是1 的直接可检判据）。

零LLM 成本，秒级。改动 oracle 或算子后必须重跑。

用法
----
    python run_f4_acceptance.py            # 全部验收
    python run_f4_acceptance.py --json      # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from vts.audit_core import (  # noqa: E402
    ORACLES,
    certify,
    make_seed_ledger,
)

# 四个主难度档对应的注入算子（其余为参照层自检用，非难度档）
MAIN_OPS = ("offbook", "cutoff", "depreciation", "capitalize")
SELFCHECK_OPS = ("equation_break", "dep_over")

# 注入金额档位：覆盖小/中/大三档，验证签名不随金额漂移
THETAS = ({}, {"amount": 1.0}, {"amount": 500.0}, {"amount": 50000.0})
N_SEEDS = 10


def check_clean() -> dict:
    """验收 1：干净账套零误报。"""
    bad = {o: 0 for o in ORACLES}
    total = 0
    for s in range(150):
        led = make_seed_ledger(1000 + s)
        for p in range(1, led.n_periods + 1):
            total += 1
            for name, fn in ORACLES.items():
                if not fn(led, p):
                    bad[name] += 1
    return {
        "n_samples": total,
        "per_oracle_fp": bad,
        "total_fp": sum(bad.values()),
        "pass": sum(bad.values()) == 0,
    }


def signatures() -> dict:
    """验收 2：收集每个算子的违反签名（跨金额档取并集）。"""
    sigs = {}
    for op in list(MAIN_OPS) + list(SELFCHECK_OPS):
        v = set()
        for th in THETAS:
            for s in range(N_SEEDS):
                d = certify(make_seed_ledger(2000 + s), op, th, f"{op}-probe")
                v |= set(d.violated)
        sigs[op] = sorted(v)
    return sigs


def check_distinguishable(sigs: dict) -> dict:
    """验收 3：主算子签名两两可区分。"""
    pairs = []
    for i in range(len(MAIN_OPS)):
        for j in range(i + 1, len(MAIN_OPS)):
            a, b = MAIN_OPS[i], MAIN_OPS[j]
            diff = sorted(set(sigs[a]) ^ set(sigs[b]))
            pairs.append({"pair": f"{a} vs {b}", "diff": diff,
                          "ok": bool(diff)})
    n_unique = len({tuple(sigs[o]) for o in MAIN_OPS})
    return {
        "n_unique_signatures": n_unique,
        "n_required": len(MAIN_OPS),
        "pairs": pairs,
        "pass": n_unique == len(MAIN_OPS) and all(p["ok"] for p in pairs),
    }


def check_oracle_coverage(sigs: dict) -> dict:
    """附加：是否有 oracle 从未被任何算子触发（死代码检测）。"""
    allv = set().union(*[set(v) for v in sigs.values()])
    never = sorted(set(ORACLES) - allv)
    return {"n_oracles": len(ORACLES), "n_exercised": len(allv),
            "never_triggered": never, "pass": not never}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    clean = check_clean()
    sigs = signatures()
    dist = check_distinguishable(sigs)
    cov = check_oracle_coverage(sigs)

    result = {"clean_ledger": clean, "signatures": sigs,
              "distinguishability": dist, "oracle_coverage": cov,
              "PASS": bool(clean["pass"] and dist["pass"] and cov["pass"])}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    print("=" * 66)
    print("F4 验收：参照 oracle 的认定分层分辨力")
    print("=" * 66)

    print("\n[1] 干净账套零误报")
    print(f"    样本 {clean['n_samples']} 个(种子,期)，"
          f"总误报 {clean['total_fp']}  {'PASS' if clean['pass'] else 'FAIL'}")
    for k, v in clean["per_oracle_fp"].items():
        mark = "OK" if v == 0 else "FALSE-POSITIVE"
        print(f"      {k:20s} {v:4d}  {mark}")

    print("\n[2] 违反签名矩阵（跨 4 档金额 × 10 seed）")
    for op in list(MAIN_OPS) + list(SELFCHECK_OPS):
        tag = "主档" if op in MAIN_OPS else "自检"
        print(f"      [{tag}] {op:16s} {sigs[op]}")

    print("\n[3] 主算子两两可区分性")
    print(f"    签名种类 {dist['n_unique_signatures']}/{dist['n_required']}"
          f"  {'PASS' if dist['pass'] else 'FAIL'}")
    for p in dist["pairs"]:
        print(f"      {p['pair']:34s} 差集={p['diff']}")

    print("\n[4] oracle 覆盖（死代码检测）")
    print(f"    oracle 总数 {cov['n_oracles']}，"
          f"被触发 {cov['n_exercised']}，从未触发 {cov['never_triggered']}")

    print("\n" + "=" * 66)
    print(f"总判定：{'PASS — A0 可以投钱' if result['PASS'] else 'FAIL — 不要跑 A0，先修参照层'}")
    print("=" * 66)

    if not result["PASS"]:
        sys.exit(1)


if __name__ == "__main__":
    main()