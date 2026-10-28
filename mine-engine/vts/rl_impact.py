"""把 verifier 漏判率翻译成 GRPO 训练后果（修正版）。

=====================================================================
本模块推翻了一个被广泛引用的直觉 —— 这条是论文的核心贡献
=====================================================================

社区通行说法（来自 Reward Engineering 博客、Huang et al. 的 GRPO 误杀论证）：

    "false negative 是更致命的错误类型 —— 组内 G=8、4 个正确解，
     verifier 错杀 1 个正确解，那个解就拿到 advantage ≈ −0.77，
     梯度主动推开它。"

这句话描述的是**单次事件**，它是对的。但把它当成"漏判率的总体后果"，
推论会是"漏判率一高就会翻转"，而这个推论**是错的**。

本模块实测（蒙特卡洛，G=8，4 个正确解，每格 30000 次采样）：

    FNR  FPR   正确解平均优势   符号翻转率
    0.0  0.0          1.000          0.000
    0.3  0.0          0.748          0.000      ← 漏判 30%，完全没翻转
    0.6  0.0          0.546          0.000
    0.9  0.0          0.409          0.000
    1.0  0.0            n/a          0.000      ← 全错：不是翻转，是无梯度

**结论一（反直觉，且可证伪）**：
    在误报率为 0 时，漏判率即使到 100% 也不会让正确解的优势变负 ——
    它只会让**一部分**正确解拿到 0 优势（与错误解同分），
    剩下活着的仍然拿强正优势，平均下来甚至仍为正。

    机制：被误杀的正确解 r=0，归一化后 advantage=(0−μ)/σ 确实为负；
    但它把 μ 也拉低了，σ 同步变化。把"存活者的高优势"和"被杀者的负优势"
    放在同一组里做期望，净效应为正。**误杀单个解 ≠ 训练方向错误。**

**结论二**：真正造成符号翻转的是**误报**，不是漏判。
    FPR=0.2 时 FNR≈0.9 开始翻转；FPR=0.5 时 FNR≈0.5 就翻转；
    FPR=0.8 时 FNR≈0.25 就翻转。

    机制：误报把**错误解**抬到和正确解同分，组内不再区分对错，
    正确解的优势被稀释到 0 以下。这是奖励污染，不是奖励缺失。

**结论三（第三种失效模式，此前被忽略）**：
    FNR→1.0 且 FPR→0 时，**65%–100% 的组完全无梯度信号**
    （组内 reward 全同，σ=0，GRPO 直接跳过这一步）。
    这不是"训练变差"，是**训练直接停摆**，而且不报错、不崩、曲线看起来正常。
    —— 这与我们在代码域发现的截断污染是同一类陷阱：
       **失效伪装成"模型能力不足"。**

因此给 verifier 写预算表时，必须**同时**报 FNR、FPR、和退化组比例三个数。
只报 FNR 会让人误以为"漏判无害"，这是危险的错误结论。

对照关系（本模块的存在意义）：
    上述三条全部只能在"有 ground-truth verifier V*"的地方测。
    Egashira et al. 明说他们 restrict to settings where V* is tractable。
    我们用 DIC 提供 V*，于是能在审计域测 —— 而审计域只能上 LLM judge，
    它的漏判率至今无人能测。
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, asdict
from pathlib import Path

from vts.verifier_audit import VERIFIERS, audit_verifier


# ---------------------------------------------------------------- GRPO 精确计算
def grpo_advantage_analysis(fnr: float, fpr: float, n_correct: int = 4,
                            group: int = 8) -> dict:
    """GRPO 组内优势的**精确期望**（枚举全部判定组合，非蒙特卡洛）。

    GRPO 优势：A_i = (r_i − mean(r)) / std(r)，组内归一化。
    σ=0 的组无梯度，记为"退化"。

    这里按"存活正确解数 k"枚举：
      P(k) = C(n_correct, k)·(1−fnr)^k·fnr^(n_correct−k) · C(n_wrong,m)·fpr^m·(1−fpr)^(n_wrong−m)
      给定 (k, m)，组内正例数 k+m，mean=(k+m)/G，正例优势=(1−mean)/σ。
    """
    n_wrong = group - n_correct

    e_correct = 0.0
    p_degen = 0.0
    for k in range(n_correct + 1):
        pk = (math.comb(n_correct, k) * (1 - fnr) ** k
              * fnr ** (n_correct - k))
        if pk == 0:
            continue
        for m in range(n_wrong + 1):
            pm = (math.comb(n_wrong, m) * fpr ** m
                  * (1 - fpr) ** (n_wrong - m))
            if pm == 0:
                continue
            pos = k + m
            mean = pos / group
            sd = math.sqrt(mean * (1 - mean))
            p = pk * pm
            if sd == 0:
                # 全 0 或全 1 → 组内无梯度，记为退化
                p_degen += p
                continue
            # (a) 幸存的 k 个正确解：r=1 → advantage (1−mean)/sd
            e_correct += p * k * ((1 - mean) / sd)
            # (b) 被误杀的 (n_correct − k) 个正确解：r=0 → (0−mean)/sd < 0
            #     这一项是整个分析的命门：第一版漏了 (n_correct − k) 乘数
            #     （每个被误杀的解都要各计一次），导致解析优势算出 1.551
            #     而 MC 是 0.236，判定逻辑全部反了。
            e_correct += p * (n_correct - k) * ((0 - mean) / sd)

    # 上面积累的是**正确解优势之和**，而报告口径要与 MC 一致：
    # 「正确解的平均优势」= 总和 / 正确解个数。
    # 少了这一步，无误差情形会给出 4.000 而不是 1.000（偏差 4 倍）。
    e_correct /= n_correct

    # 精确率：verifier 判"正确"里有多少是真的
    tp = n_correct * (1 - fnr)
    fp = n_wrong * fpr
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0

    return {
        "fnr": round(fnr, 4), "fpr": round(fpr, 4),
        "group": group, "n_correct": n_correct,
        "correct_advantage": round(e_correct, 4),
        "degenerate_group_pct": round(p_degen, 4),
        "precision": round(precision, 4),
        "verdict": ("NO_SIGNAL" if p_degen >= 0.5
                    else "SIGN_FLIP" if e_correct < 0 else "OK"),
    }


def mc_check(fnr: float, fpr: float, n_correct: int = 4, group: int = 8,
             trials: int = 30000, seed: int = 3) -> dict:
    """蒙特卡洛独立校验解析式。两者不一致时以 MC 为准并报警。"""
    rng = random.Random(seed)
    tot = 0.0
    flip = degen = used = 0
    tp_sum = fp_sum = 0.0
    for _ in range(trials):
        rewards, truth = [], []
        for i in range(group):
            corr = i < n_correct
            r = 1 if (corr and rng.random() >= fnr) or \
                   (not corr and rng.random() < fpr) else 0
            rewards.append(r)
            truth.append(1 if corr else 0)
        mu = sum(rewards) / group
        sd = math.sqrt(sum((r - mu) ** 2 for r in rewards) / group)
        if sd == 0:
            degen += 1
            continue
        adv = [(r - mu) / sd for r in rewards]
        pos = [adv[i] for i in range(group) if truth[i] == 1]
        if not pos:
            continue
        m = sum(pos) / len(pos)
        tot += m
        used += 1
        if m < 0:
            flip += 1
        for i in range(group):
            if rewards[i] == 1:
                if truth[i]:
                    tp_sum += 1
                else:
                    fp_sum += 1
    return {
        "fnr": fnr, "fpr": fpr, "trials": trials,
        "mc_correct_advantage": round(tot / used, 4) if used else None,
        "mc_sign_flip_rate": round(flip / trials, 4),
        "mc_degenerate_rate": round(degen / trials, 4),
        "mc_precision": round(tp_sum / (tp_sum + fp_sum), 4)
                         if (tp_sum + fp_sum) else 1.0,
    }


def flip_threshold(fpr: float, n_correct: int = 4, group: int = 8,
                   tol: float = 1e-4) -> dict:
    """二分求"正确解平均优势变负"的漏判率阈值。

    只在 fpr > 0 时存在 —— fpr = 0 时阈值不收敛（见模块 docstring 结论一）。
    """
    if fpr <= 0:
        return {"fpr": fpr, "fnr_threshold": None,
                "note": "误报率为 0 时不存在翻转阈值：漏判率升到 1.0 也不翻转，"
                        "但会进入无梯度退化区。"}
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if grpo_advantage_analysis(mid, fpr, n_correct, group
                                   )["correct_advantage"] > tol:
            lo = mid
        else:
            hi = mid
    return {"fpr": fpr, "fnr_threshold": round(lo, 4),
            "note": "漏判率超过此值，正确解平均优势变负 → 梯度推开正确答案。"}


@dataclass
class BudgetRow:
    verifier: str
    fnr: float
    fpr: float
    correct_advantage: float
    degenerate_pct: float
    precision: float
    verdict: str


def run(n_seeds: int = 150) -> dict:
    audits = [audit_verifier(v, n_seeds) for v in VERIFIERS.values()]
    rows = []
    for a in audits:
        ana = grpo_advantage_analysis(a.fnr, a.det_fnr_clean_fp)
        rows.append(BudgetRow(a.name, a.fnr, a.det_fnr_clean_fp,
                              ana["correct_advantage"],
                              ana["degenerate_group_pct"],
                              ana["precision"], ana["verdict"]))
    thresholds = [flip_threshold(f) for f in (0.0, 0.05, 0.1, 0.2, 0.35, 0.5)]

    # 解析式 vs MC 的对照网格
    grid = []
    for fpr in (0.0, 0.2, 0.5, 0.8):
        for fnr in (0.0, 0.3, 0.6, 0.9):
            ana = grpo_advantage_analysis(fnr, fpr)
            mc = mc_check(fnr, fpr, trials=8000)
            grid.append({
                "fnr": fnr, "fpr": fpr,
                "analytic_adv": ana["correct_advantage"],
                "mc_adv": mc["mc_correct_advantage"],
                "analytic_degen": ana["degenerate_group_pct"],
                "mc_degen": mc["mc_degenerate_rate"],
                "verdict": ana["verdict"],
            })
    return {
        "verifier_budget": [asdict(r) for r in rows],
        "flip_thresholds": thresholds,
        "analytic_vs_mc": grid,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=150)
    ap.add_argument("--out", default="results_e8_rl_impact.json")
    args = ap.parse_args()

    r = run(args.seeds)

    print("=" * 80)
    print("1. 实测 verifier → GRPO 训练后果（G=8，4 个正确解）")
    print(f"{'verifier':<20}{'FNR':>7}{'FPR':>7}"
          f"{'正确解优势':>12}{'退化组':>9}{'精确率':>8}  判定")
    for b in r["verifier_budget"]:
        print(f"{b['verifier']:<20}{b['fnr']:>7.3f}{b['fpr']:>7.3f}"
              f"{b['correct_advantage']:>12.3f}{b['degenerate_pct']:>9.3f}"
              f"{b['precision']:>8.3f}  {b['verdict']}")
    print("  OK=梯度正常  SIGN_FLIP=梯度推开正确答案  NO_SIGNAL=组内无梯度")

    print("=" * 80)
    print("2. 符号翻转阈值：什么条件下漏判才真的翻转训练方向")
    for t in r["flip_thresholds"]:
        if t["fnr_threshold"] is None:
            print(f"   FPR={t['fpr']:.2f}  →  {t['note']}")
        else:
            print(f"   FPR={t['fpr']:.2f}  →  漏判率阈值 = {t['fnr_threshold']:.4f}")
    print("\n   ** 误报为 0 时不存在翻转阈值。造成翻转的是误报，不是漏判。 **")

    print("=" * 80)
    print("3. 解析式 vs 蒙特卡洛（校验公式可信）")
    print(f"{'FNR':>5}{'FPR':>6}{'解析优势':>10}{'MC优势':>10}"
          f"{'解析退化':>10}{'MC退化':>9}  判定")
    max_gap = 0.0
    for g in r["analytic_vs_mc"]:
        gap = abs(g["analytic_adv"] - g["mc_adv"])
        max_gap = max(max_gap, gap)
        print(f"{g['fnr']:>5.1f}{g['fpr']:>6.1f}{g['analytic_adv']:>10.3f}"
              f"{g['mc_adv']:>10.3f}{g['analytic_degen']:>10.3f}"
              f"{g['mc_degen']:>9.3f}  {g['verdict']}")
    print(f"\n   最大偏差 = {max_gap:.3f}（<0.15 视为解析式可信）")

    print("=" * 80)
    print("4. 第三种失效模式（此前被忽略）：无梯度退化")
    for g in r["analytic_vs_mc"]:
        if g["fnr"] >= 0.9 and g["fpr"] == 0.0:
            print(f"   FNR={g['fnr']:.1f}, FPR=0  →  "
                  f"{g['analytic_degen']*100:.0f}% 的组无梯度信号")
    print("   组内 reward 全同 → σ=0 → GRPO 跳过。")
    print("   不报错、不崩、训练曲线看起来正常 —— 失效伪装成能力不足。")

    Path(args.out).write_text(json.dumps(r, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print("=" * 80)
    print(f"已写出 {args.out}")


if __name__ == "__main__":
    main()
