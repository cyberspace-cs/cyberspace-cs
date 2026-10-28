"""S1.1 + S2：把 S1 实测的 judge 误差接进 rl_impact，看 GRPO 的真实后果。

为什么必须先做这一步
--------------------
`rl_impact.py` 至今跑的是 7 个**我们自己写的** verifier，
它的 (FNR, FPR) 来自 `verifier_audit.py` 里的 `DEFAULT_PROFILE`——
那是我们假设的答案分布，不是测出来的。

S1（docs/20-S1实测报告.md）给出了第一批**真实 LLM judge** 的误差，
于是现在可以把"假设参数"换成"实测参数"。这一步做完，
论文里那张"verifier 误差 → 训练后果"的表才第一次有真实落点，
而不再是自洽的假设推演。

两个实测点（arm C，最宽松配置；端到端口径）
------------------------------------------
    deepseek-flash   FNR = 0.500   FPR = 0.000   （n=160）
    deepseek-v4-pro  FNR = 0.380   FPR = 0.800   （n=100）

口径说明（重要，别搞错）
------------------------
RL 里的 reward 通常直接取 judge 的判定 flag。于是：

    正确解轨迹（agent 发现并正确归因异常）
        → judge 判对的概率 = 1 − FNR(端到端)
    错误解轨迹（agent 说没问题 / 归因错）
        → judge 误判为对的概率 = FPR

这正是 `grpo_advantage_analysis(fnr, fpr, ...)` 的两个入参，
所以可以直接接，不需要额外的映射假设。

为什么这两个点特别值得算
------------------------
它们**恰好落在结论一和结论二的两侧**，是一次天然对照：

    flash  FPR = 0     → 按结论一：FNR 再高也不翻转，但会大量退化
    pro    FPR = 0.800 → 按结论二：翻转阈值约 0.25，而它 FNR = 0.38 > 0.25
                          ⇒ **更强的模型反而会把训练方向带反**

如果这个对照成立，"买更强的 judge 不等于买更好的 RL"就从一个说法
变成了一个可算、可验证的结论。

S2 一并做了
-----------
组大小敏感性 G ∈ {4, 8, 16, 32}（n_correct 保持 G/2），
审稿人一定会问"阈值是不是只在 G=8 这一格成立"。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from vts.rl_impact import (flip_threshold, grpo_advantage_analysis,
                           mc_check)

# S1 实测点：来源 docs/20-S1实测报告.md §3.3（arm C，端到端，多数票）
REAL_JUDGES = {
    "deepseek-flash": {"fnr": 0.500, "fpr": 0.000, "n": 160,
                       "ci": [0.423, 0.577],
                       "note": "检测层 0.494 / 归因层 0.012"},
    "deepseek-v4-pro": {"fnr": 0.380, "fpr": 0.800, "n": 100,
                        "ci": [0.291, 0.478],
                        "note": "检测层 0.070 / 归因层 0.333"},
}

GROUPS = (4, 8, 16, 32)


def verdict_of(adv: float, degen: float) -> str:
    if degen >= 0.5:
        return "NO_SIGNAL"
    return "SIGN_FLIP" if adv < 0 else "OK"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=30000,
                    help="每个点的蒙特卡洛次数（用于校验解析式）")
    ap.add_argument("--out", default="results_s11_rl_impact_real.json")
    args = ap.parse_args()

    out: dict = {"source": "S1 实测 (docs/20) · arm C · 端到端口径",
                 "judges": {}, "group_sensitivity": {},
                 "flip_thresholds": {}}

    print("=" * 78)
    print("S1.1：把实测 judge 误差接进 GRPO 后果模型")
    print("=" * 78)
    print(f"{'judge':<16}{'FNR':>6}{'FPR':>6}{'正确解优势':>12}"
          f"{'退化组':>9}{'精确率':>9}  判定")

    for name, d in REAL_JUDGES.items():
        ana = grpo_advantage_analysis(d["fnr"], d["fpr"])
        mc = mc_check(d["fnr"], d["fpr"], trials=args.trials)
        row = {
            **d,
            "correct_advantage": ana["correct_advantage"],
            "degenerate_pct": ana["degenerate_group_pct"],
            "precision": ana["precision"],
            "verdict": verdict_of(ana["correct_advantage"],
                                  ana["degenerate_group_pct"]),
            "mc_advantage": mc["mc_correct_advantage"],
            "mc_degenerate": mc["mc_degenerate_rate"],
        }
        out["judges"][name] = row
        print(f"{name:<16}{d['fnr']:>6.3f}{d['fpr']:>6.3f}"
              f"{ana['correct_advantage']:>12.4f}"
              f"{ana['degenerate_group_pct'] * 100:>8.1f}%"
              f"{ana['precision']:>9.3f}  {row['verdict']}")
        print(f"{'':<16}MC 校验 优势={mc['mc_correct_advantage']:.4f} "
              f"退化={mc['mc_degenerate_rate'] * 100:.1f}%")

    # ---- 翻转阈值：每个实测 judge 离翻转还有多远
    print()
    print("翻转阈值（FPR 固定为该 judge 的实测值）")
    for name, d in REAL_JUDGES.items():
        th = flip_threshold(d["fpr"])
        out["flip_thresholds"][name] = th
        if th["fnr_threshold"] is None:
            print(f"  {name:<16}FPR={d['fpr']:.3f}  "
                  f"→ 无翻转阈值：漏判到 1.0 也不翻转，只进入退化区")
        else:
            gap = th["fnr_threshold"] - d["fnr"]
            print(f"  {name:<16}FPR={d['fpr']:.3f}  "
                  f"→ FNR 阈值={th['fnr_threshold']:.3f}  "
                  f"实测 FNR={d['fnr']:.3f}  "
                  f"余量={gap:+.3f} "
                  f"{'（已越线：方向被带反）' if gap < 0 else '（未越线）'}")

    # ---- S2：组大小敏感性
    print()
    print("=" * 78)
    print("S2：组大小敏感性（n_correct = G/2）")
    print("=" * 78)
    print(f"{'judge':<16}{'G':>4}{'n_correct':>10}{'优势':>10}"
          f"{'退化组':>9}  判定")
    for name, d in REAL_JUDGES.items():
        out["group_sensitivity"][name] = []
        for g in GROUPS:
            nc = g // 2
            ana = grpo_advantage_analysis(d["fnr"], d["fpr"],
                                          n_correct=nc, group=g)
            v = verdict_of(ana["correct_advantage"],
                           ana["degenerate_group_pct"])
            out["group_sensitivity"][name].append({
                "G": g, "n_correct": nc,
                "correct_advantage": ana["correct_advantage"],
                "degenerate_pct": ana["degenerate_group_pct"],
                "verdict": v,
            })
            print(f"{name:<16}{g:>4}{nc:>10}"
                  f"{ana['correct_advantage']:>10.4f}"
                  f"{ana['degenerate_group_pct'] * 100:>8.1f}%  {v}")

    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
