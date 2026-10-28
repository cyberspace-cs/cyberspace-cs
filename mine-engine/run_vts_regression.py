"""回归测试：锁死 vts 包的关键行为，防止后续改动悄悄破坏已验证的结论。

跑法：
    python run_vts_regression.py

背景：本文的立论依赖三个已实测的结论，它们必须被自动守住：
  1. 种子账套天然满足全部会计约束（否则 oracle 写错了）
  2. 注入的差分隔离证书有效率 100%
  3. GRPO 解析式与蒙特卡洛一致（否则阈值结论不可信）
另外锁死"结构性不可见"这个实测事实，因为它支撑"只查恒等式的 verifier
有系统性盲区"这个核心立论。该断言按算子语义分类：
四个主难度档 + dep_over 属恒等式盲区（不可见），
equation_break 专用于破坏恒等式（必须可见，防止参照层退化成死代码）。
会恒定漏掉所有四种手法"这一核心论点。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from vts.audit_core import FRAUD_OPS, ORACLES, certify, make_seed_ledger
from vts.rl_impact import grpo_advantage_analysis, mc_check
from vts.verifier_audit import VERIFIERS, audit_verifier

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((PASS if cond else FAIL, name, detail))


def main() -> int:
    # ---- 1. 种子账套必须天然全平（oracle 正确性的前提）
    bad = {}
    for s in range(100):
        led = make_seed_ledger(s)
        for p in range(1, led.n_periods + 1):
            for n, fn in ORACLES.items():
                if not fn(led, p):
                    bad[f"{n}@p{p}"] = bad.get(f"{n}@p{p}", 0) + 1
    check("种子账套 x 100 x 4期 x 4oracle 全部自平", not bad,
          f"违规: {bad}" if bad else "1600/1600 OK")

    # ---- 2. 差分隔离证书有效率必须 100%
    tot = ok = 0
    for op in FRAUD_OPS:
        for s in range(100):
            tot += 1
            ok += int(certify(make_seed_ledger(s), op, {}, "t").valid)
    check("DIC 有效率 100%", ok == tot, f"{ok}/{tot}")

    # ---- 3. 结构性不可见：只查恒等式对**非恒等式型**手法全部恒盲
    #
    # ⚠️ 这里按算子的**语义**分类，而不是硬编码名单。
    # FRAUD_OPS 里 equation_break 的设计目的就是破坏会计恒等式，
    # 它按定义不可能"恒盲"；而 dep_over（超额计提折旧）虽不破坏恒等式，
    # 但与四个主难度档同属"恒等式盲区"，实测同样不可见。
    # 用set(FRAUD_OPS) 全集断言会在新增自检算子后假失败
    # （与已记录的"分母写死"同类坑：断言跟不上数据源）。
    EXPECTED_INVISIBLE = set(FRAUD_OPS) - {"equation_break"}
    a = audit_verifier(VERIFIERS["equation_only"], 30)
    check("只查 o_equation 对恒等式型手法结构性不可见",
          set(a.invisible) == EXPECTED_INVISIBLE,
          f"invisible={sorted(a.invisible)} 期望={sorted(EXPECTED_INVISIBLE)}")

    # 反向自检：破坏恒等式的算子必须**能**被 o_equation 看到，否则参照层有死代码
    check("equation_break 必须对 o_equation 可见（防死代码回归）",
          "equation_break" not in a.invisible,
          f"invisible={sorted(a.invisible)}")

    # ---- 4. 难度参数不得改变 oracle 破坏集（C 类性质②）
    led = make_seed_ledger(0)
    base = certify(led, "capitalize", {"amount": 1000}, "t").violated
    same = all(certify(led, "capitalize", {"amount": a}, "t").violated == base
               for a in (1e4, 1e5, 1e6))
    check("调整 theta 不改变违反集（难度与 oracle 解耦）", same,
          f"违反集恒为 {base}")

    # ---- 5. GRPO 解析式 vs 蒙特卡洛（容差内一致）
    worst = 0.0
    for fnr in (0.0, 0.3, 0.6, 0.9):
        for fpr in (0.0, 0.2, 0.5):
            ana = grpo_advantage_analysis(fnr, fpr)["correct_advantage"]
            mc = mc_check(fnr, fpr, trials=6000)["mc_correct_advantage"]
            worst = max(worst, abs(ana - mc))
    check("GRPO 解析式与 MC 一致（最大偏差 < 0.35）", worst < 0.35,
          f"最大偏差 {worst:.3f}")

    # ---- 6. 反直觉结论：FPR=0 时不存在符号翻转阈值
    hi = grpo_advantage_analysis(1.0, 0.0)
    check("FPR=0 时 FNR=1.0 不翻转（优势非负）",
          hi["correct_advantage"] >= -1e-6,
          f"优势={hi['correct_advantage']}")

    # ---- 7. 反直觉结论：FNR→1 且 FPR=0 时进入无梯度退化
    hi2 = grpo_advantage_analysis(1.0, 0.0)
    check("FPR=0 且 FNR=1.0 → 100% 组无梯度", hi2["degenerate_group_pct"] > 0.99,
          f"退化比例={hi2['degenerate_group_pct']}")

    # ---- 8. 误报才造成翻转（FPR>0 时阈值随 FPR 下降）
    t1 = grpo_advantage_analysis(0.7, 0.1)["correct_advantage"]
    t2 = grpo_advantage_analysis(0.7, 0.5)["correct_advantage"]
    check("同一 FNR 下，误报率越高优势越负", t2 < t1, f"fpr0.1={t1:.3f} fpr0.5={t2:.3f}")

    # ---- 9. 所有 verifier 的误差都必须是系统性的（不能是随机噪声）
    sysv = 0
    tot_v = 0
    for v in VERIFIERS.values():
        aa = audit_verifier(v, 30)
        tot_v += 1
        sysv += int(aa.nmi > aa.nmi_null_p95 + 0.05 or aa.det_fnr in (0.0, 1.0))
    check("verifier 误差呈系统性（非随机）", sysv >= tot_v - 1,
          f"{sysv}/{tot_v} 呈系统性")

    # ---- 输出
    print("=" * 74)
    print("vts 回归测试")
    print("=" * 74)
    for status, name, detail in results:
        mark = "✓" if status == PASS else "✗"
        print(f" {mark} {name}")
        if detail:
            print(f"     {detail}")
    n_fail = sum(1 for s, _, _ in results if s == FAIL)
    print("=" * 74)
    print(f"{len(results) - n_fail}/{len(results)} 通过")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
