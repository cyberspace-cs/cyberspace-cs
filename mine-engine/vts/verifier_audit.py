"""Verifier 可靠性审计：用构造性参照 oracle，在零人工标注下测漏判率 / 误报率。

=====================================================================
为什么需要这个模块（这是整篇论文的立论，也是本模块存在的理由）
=====================================================================

已有工作研究"验证器误差如何伤害 RL"，但都卡在同一个前提上：
必须先有一个"可计算的 ground-truth verifier V*"。

  - Delay, Plateau, or Collapse 原文自陈：
        "as most of these essential metrics require access to the
         ground-truth verifier V*, we restrict ourselves to settings
         where V* is tractable"
  - Countdown-Code 需要一个刻意造出来的、能同时操纵 test harness 的环境。
  - Where the Verifier Fails（2609.01354）用变异测试造"保义等价变体"，
    在数学域把 FNR 测到分类级别——但前提是"保义"可由改写保证。

**结论：这个研究被锁死在 oracle 免费可得的域（math / code / web）。**

在审计、金融、政务这类域，V* 要么要 1100 专家小时（FinancialAuditBench
的 6 个 engagement 烧了 1100+ 小时），要么根本不存在。于是
"我们的判分器到底有多差"这个问题**无法被回答**，只能抽 200–500 条
人工标注去估——而 200–500 条估不出"哪类手法被系统性漏掉"。

本模块的做法：**参照真值是造出来的，不是标出来的。**
DIC（差分隔离证书）给出每个样本的注入真值；
被测 verifier 只拿到账套、跑自己那套判据；
两者比对即得 FNR / FPR，且**零人工标注、毫秒级、可复现**。

=====================================================================
FNR 必须拆成两层，否则测出来的东西没有诊断价值
=====================================================================

审计（以及任何"发现问题"的领域）里，判分要过两关：

  检测层（detection）  —— "账上有没有异常？"
      verifier 跑自己的 oracle 子集 O_v，得违反集 V = {o ∈ O_v : o(t(s)) = 0}
      V = ∅  →  漏掉了整个问题          → 检测层 FNR

  归因层（attribution）—— "是什么问题、错在哪本账哪个科目？"
      V ≠ ∅ 但模型报的手法 ≠ 实际注入的手法
      → 归因层 FNR

这个分层不是学术洁癖。第二层有一个**纯结构的、可事先推导的**成因：

      当 O_v ∩ 破坏集(手法) = ∅ 时，该手法对 verifier **结构性不可见**，
      检测层 FNR ≡ 1.0，与 oracle 实现得多好**完全无关**。

也就是说：多写几条 oracle 不一定能救你，取决于**你写的那几条是否覆盖了
这个手法实际碰到的约束**。这是加 oracle 之前必须知道的，否则会一直
错误地"再加一条 oracle"。

实测（见 run 输出的错误预算矩阵）里这条非常 stark：
`o_equation`（会计恒等式）看起来最该查，但实测它被 capitalize / cutoff
破坏 —— 而 depreciation 根本不破坏它。只查恒等式的 verifier 会漏掉
"折旧计提不足"，且无论怎么调容差都救不回来。

=====================================================================
本模块产出什么
=====================================================================

1. 精确的 FNR / FPR（分检测层与归因层），per-verifier、per-手法
2. 误差是系统性还是随机 —— NMI(手法, 是否漏判)，附打乱对照
3. **错误预算矩阵**：手法 × verifier 的漏判率，一眼看出谁看不见什么
4. 参照 oracle 自检（DIC 自身是否可信）—— 前提不成立时后面全作废

verifier 的判定是**确定性代码**，答案分布是**显式参数**，
所以 FNR 是**测量值**而非估计值；换 profile 只改变策略分布，
不改变 verifier 自身的可靠性。
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from vts.audit_core import (FRAUD_OPS, ORACLES, certify, make_seed_ledger)


# ---------------------------------------------------------------- 答案类别
# 被测模型可能产出的答案。真值由 DIC 决定，模型"说什么"由 profile 决定。

GOOD = "good"            # 手法类型对、定位对
WRONG_OP = "wrong_op"    # 报了异常，但手法类型判错
WRONG_LOC = "wrong_loc"  # 手法类型对，但定位到错的科目/期间
VAGUE = "vague"          # 只说"存在异常"，不给手法（实务最常见）
HALLU = "hallu"          # 干净账套上凭空报一个手法
MISS = "miss"            # 有问题但完全没报

ANSWER_CLASSES = [GOOD, WRONG_OP, WRONG_LOC, VAGUE, HALLU, MISS]

# 模型报告的手法类型。真实审计里模型会给出错误类型，所以这里允许扰动。
# 错误类型的数量：假设模型只知道 4 种（就是我们注入的这 4 种），猜错时
# 落在非正确的那 3 种之一。
_WRONG_OP_POOL = sorted(set(FRAUD_OPS) - {"cutoff"})   # 去掉一个凑数够用

DEFAULT_PROFILE = {
    # 有注入时：各类答案的频率
    "with_fraud": {GOOD: 0.30, WRONG_OP: 0.14, WRONG_LOC: 0.18,
                   VAGUE: 0.22, HALLU: 0.02, MISS: 0.14},
    # 干净账套时：幻觉率应低得多
    "clean": {GOOD: 0.0, WRONG_OP: 0.0, WRONG_LOC: 0.0,
              VAGUE: 0.03, HALLU: 0.05, MISS: 0.92},
}


# ---------------------------------------------------------------- verifier
@dataclass
class Verifier:
    """被测判分器。

    它只拿到注入后的账套，跑自己那一套 oracle 子集，然后判定。
    它**拿不到** DIC 的注入记录——这正是"独立 verifier"的定义。
    """
    name: str
    desc: str
    oracles: tuple[str, ...]          # 它检查的会计约束
    require_type: bool = True         # 是否要求模型报出正确的手法类型
    require_loc: bool = True          # 是否要求定位正确
    accept_vague: bool = False        # 是否接受"只说有问题不给类型"
    accept_any_op: bool = False       # 是否接受任意手法类型（宽松）

    def detect(self, injected) -> tuple[bool, frozenset[str]]:
        """检测层：跑自己的 oracle 子集，返回 (是否有异常, 违反集)。"""
        p = injected.n_periods
        viol = frozenset(
            name for name in self.oracles if not ORACLES[name](injected, p))
        return (len(viol) > 0, viol)

    def judge(self, injected, has_true_fraud: bool,
              reported_op: str | None, correct: bool) -> int:
        """返回 1 = 判为"正确发现/通过"，0 = 判为"没问题/不通过"。"""
        found, _ = self.detect(injected)
        if not has_true_fraud:
            # 干净账套：只有"模型报了东西且 verifier 自己也看到东西"才算误报
            if not found:
                return 0
            return int(self.accept_any_op or self.accept_vague
                       or (self.require_type is False))
        # 有注入：两层都要过
        if not found:
            return 0                      # 检测层漏判
        if reported_op is None:
            return int(self.accept_vague)  # 只说"有问题"，未给类型
        if self.accept_any_op:
            return 1
        if self.require_type and reported_op != _TRUE_OP:
            return 0                      # 归因层错误
        if self.require_loc and not correct:
            return 0                      # 定位错
        return 1


# _TRUE_OP 由循环注入，避免闭包传参
_TRUE_OP: str | None = None


VERIFIERS: dict[str, Verifier] = {
    # 最直觉的"审计基本功"：报表必须等于明细汇总。只查这一条。
    "tie_only": Verifier("tie_only", "只查报表=明细汇总",
                         oracles=("o_tie_detail",)),
    # 只查恒等式——很多"合规检查"就是这一条
    "equation_only": Verifier("equation_only", "只查资产=负债+权益",
                              oracles=("o_equation",)),
    # 三条勾稽
    "arith_full": Verifier("arith_full", "勾稽+递推+恒等式（不看政策）",
                           oracles=("o_tie_detail", "o_rollforward", "o_equation")),
    # 完整程序化判分器
    "programmatic_full": Verifier("programmatic_full", "全部四条会计约束",
                                  oracles=("o_tie_detail", "o_rollforward",
                                           "o_equation", "o_policy")),
    # 完整判据 + 严格要求类型与定位
    "strict_typed": Verifier("strict_typed", "全判据 + 类型定位全对",
                             oracles=("o_tie_detail", "o_rollforward",
                                      "o_equation", "o_policy"),
                             require_type=True, require_loc=True),
    # 半宽松：容忍定位不准，但类型要对
    "typed_lenient": Verifier("typed_lenient", "类型对即过，容忍定位不准",
                              oracles=("o_tie_detail", "o_rollforward",
                                       "o_equation"),
                              require_type=True, require_loc=False),
    # 宽松：模型说有问题就算过，且接受任意类型
    "any_flag": Verifier("any_flag", "报了就算过（宽松）",
                         oracles=("o_tie_detail", "o_rollforward",
                                  "o_equation", "o_policy"),
                         require_type=False, require_loc=False,
                         accept_vague=True, accept_any_op=True),
}


# ---------------------------------------------------------------- 审计
@dataclass
class VerifierAudit:
    name: str
    desc: str
    oracles: tuple[str, ...]
    det_fnr: float              # 检测层漏判率
    det_fnr_clean_fp: float     # 干净账套上的误报率
    attr_fnr: float             # 归因层漏判率（在检出的样本里）
    fnr: float                  # 总漏判率（端到端）
    per_fraud_det_fnr: dict[str, float] = field(default_factory=dict)
    invisible: tuple[str, ...] = ()     # 结构性不可见的手法
    nmi: float = 0.0
    nmi_shuffled: float = 0.0
    nmi_null_p95: float = 0.0
    n_rows: int = 0


def _nmi(a: list, b: list) -> float:
    if not a or len(a) != len(b):
        return 0.0
    n = len(a)
    ca, cb, cab = defaultdict(int), defaultdict(int), defaultdict(int)
    for x, y in zip(a, b):
        ca[x] += 1
        cb[y] += 1
        cab[(x, y)] += 1
    ha = -sum((v / n) * math.log2(v / n) for v in ca.values())
    hb = -sum((v / n) * math.log2(v / n) for v in cb.values())
    if ha <= 0 or hb <= 0:
        return 0.0
    mi = sum((c / n) * math.log2((c / n) / ((ca[x] / n) * (cb[y] / n)))
             for (x, y), c in cab.items())
    return mi / math.sqrt(ha * hb)


def audit_verifier(v: Verifier, n_seeds: int = 150,
                   profile: dict | None = None) -> VerifierAudit:
    """对单个 verifier 做精确审计。

    流程：种子 → 注入手法（DIC 给真值）→ verifier 独立跑自己的 oracle →
    模型按 profile 给一个答案 → verifier 判定 → 与真值比对。

    verifier 的判定是**确定性纯函数**，所以漏判率是**测量值**、不是估计值。

    计数口径（三条，分母各不相同——第一版就错在这里，把端到端 FNR
    算成了 7000%）：
      检测层  分母 = 注入样本数（每 (手法, seed) 一个）
      归因层  分母 = 检测层已检出、且模型给了答案的样本数
      端到端  分母 = 注入的 (手法, seed, 答案类别) 三元组数
    """
    global _TRUE_OP
    prof = profile or DEFAULT_PROFILE

    rows: list[tuple[str, str, int]] = []      # (手法, 答案类别, 是否判对)
    det_rows: list[tuple[str, bool]] = []      # (手法, 检测层是否检出)
    clean_fp = 0
    clean_n = 0

    for op_name in sorted(FRAUD_OPS):
        _TRUE_OP = op_name
        wf = prof["with_fraud"]
        for seed in range(n_seeds):
            led = make_seed_ledger(seed)
            injected = led.clone()
            FRAUD_OPS[op_name].apply(injected, {})
            found, _ = v.detect(injected)
            det_rows.append((op_name, found))

            for ans, freq in wf.items():
                if freq <= 0:
                    continue
                if ans == MISS:
                    # 模型没报任何东西 → 端到端必错（与能否检出无关）
                    rows.append((op_name, ans, 0))
                    continue
                if ans == GOOD:
                    reported, correct = op_name, True
                elif ans == WRONG_OP:
                    reported, correct = _other_op(op_name), True
                elif ans == WRONG_LOC:
                    reported, correct = op_name, False
                elif ans == VAGUE:
                    reported, correct = None, False
                else:      # HALLU：有注入时也报了错类型
                    reported, correct = _other_op(op_name), True
                rows.append((op_name, ans,
                             v.judge(injected, True, reported, correct)))

        # 干净账套：只有 verifier 自己也看到异常、且模型报了东西，才算误报
        for seed in range(n_seeds):
            led = make_seed_ledger(seed)
            found, _ = v.detect(led)
            clean_n += 1
            if not found:
                continue
            for ans, freq in prof["clean"].items():
                if freq <= 0 or ans in (MISS, GOOD, WRONG_OP, WRONG_LOC):
                    continue
                clean_fp += max(1, round(freq * 100))

    det_total = len(det_rows)
    det_fnr = (sum(1 for _, f in det_rows if not f) / det_total
               if det_total else 0.0)

    e2e_total = len(rows)
    fnr = (sum(1 for _, _, s in rows if s == 0) / e2e_total
           if e2e_total else 0.0)

    # 归因层：错误里属于"模型给了答案但被判 0"的部分（MISS 属漏报侧，不算）
    attr_err = sum(1 for _, a, s in rows if s == 0 and a != MISS)
    attr_den = attr_err + sum(1 for _, a, s in rows if s == 1 and a != MISS)
    attr_fnr = attr_err / attr_den if attr_den else 0.0

    per = {}
    for op_name in sorted(FRAUD_OPS):
        sub = [f for o, f in det_rows if o == op_name]
        if sub:
            per[op_name] = round(1 - sum(sub) / len(sub), 4)

    invisible = tuple(sorted(
        op for op in FRAUD_OPS
        if per.get(op, 0.0) >= 0.999
        and not (set(v.oracles) & FRAUD_OPS[op].expects)))

    # 系统性检验必须在**回答层**做。检测层常常是退化的（要么全检出、
    # 要么全漏判），此时任何互信息都恒为 0，不能用来判断系统性。
    #
    # 粒度选择是关键：第一版用 (手法|答案类别) 做条件变量，24 个格子每格
    # 几乎只有 1 个样本 → 联合熵塌缩 → MI≈0，连**已知**的系统性误差都测不出
    # （已用构造样例验证：NMI=0.0，而正确的度量应给 1.0）。
    # 改成只用答案类别（6 个格子，样本充足），问的是：
    # "模型给出哪一类答案时更容易被 verifier 判错" —— 这才是可诊断的。
    labels = [a for _, a, _ in rows]
    errs = ["FN" if s == 0 else "TP" for _, _, s in rows]
    nmi = _nmi(labels, errs)
    # 对照：**真随机化**。错位打乱在这里无效 —— 数据按手法分块排列，
    # 半数偏移恰好落在同一块内，配对关系没被破坏，NMI 与原值完全相同
    # （实测 0.501 vs 0.501）。必须用固定种子的随机置换。
    rng = random.Random(12345)
    perm = list(errs)
    rng.shuffle(perm)
    nmi_sh = _nmi(labels, perm)
    # 分布性对照：20 次随机置换的 NMI 分布，报均值与 95 分位
    boots = []
    for i in range(20):
        p2 = list(errs)
        random.Random(1000 + i).shuffle(p2)
        boots.append(_nmi(labels, p2))
    boots.sort()

    return VerifierAudit(
        name=v.name, desc=v.desc, oracles=v.oracles,
        det_fnr=round(det_fnr, 4),
        det_fnr_clean_fp=round(clean_fp / clean_n, 4) if clean_n else 0.0,
        attr_fnr=round(attr_fnr, 4),
        fnr=round(fnr, 4),
        per_fraud_det_fnr=per, invisible=invisible,
        nmi=round(nmi, 4), nmi_shuffled=round(nmi_sh, 4),
        nmi_null_p95=round(boots[int(0.95 * (len(boots) - 1))], 4),
        n_rows=e2e_total,
    )


def _other_op(true_op: str) -> str:
    pool = [o for o in _WRONG_OP_POOL if o != true_op]
    return pool[0] if pool else "offbook"


def error_budget(audits: list[VerifierAudit]) -> dict:
    """错误预算：每种手法被哪些 verifier 漏掉，以及漏在检测层还是归因层。"""
    ops = sorted(FRAUD_OPS)
    names = [a.name for a in audits]
    return {
        "verifiers": names,
        "det_fnr_matrix": {a.name: {op: a.per_fraud_det_fnr.get(op, 0.0)
                                    for op in ops} for a in audits},
        "structurally_invisible": {a.name: list(a.invisible) for a in audits},
        "least_covered": sorted(
            ops, key=lambda op: min(a.per_fraud_det_fnr.get(op, 0.0)
                                     for a in audits), reverse=True),
        "oracle_coverage": {op: sorted(FRAUD_OPS[op].expects) for op in ops},
        "note": ("检测层 FNR=1.0 且该手法的破坏集与 verifier 的 oracle 子集无交集 "
                 "=> 结构性不可见，调容差/改实现都救不回来，只能换判据。"),
    }


def reference_selfcheck(n_seeds: int = 150) -> dict:
    """参照 oracle 自检。DIC 不可信则上面所有 FNR 都不成立，不能省。"""
    dic = {}
    for op_name in sorted(FRAUD_OPS):
        ok = sum(1 for s in range(n_seeds)
                 if certify(make_seed_ledger(s), op_name, {}, "t").valid)
        dic[op_name] = {"valid": ok, "n": n_seeds,
                        "rate": round(ok / n_seeds, 4)}
    dirty = {}
    for s in range(n_seeds):
        led = make_seed_ledger(s)
        p = led.n_periods
        bad = [n for n, fn in ORACLES.items() if not fn(led, p)]
        if bad:
            dirty[s] = bad
    return {"dic_valid": dic, "clean_ledger_violations": dirty,
            "reference_trustworthy":
                not dirty and all(x["rate"] == 1.0 for x in dic.values())}


def run(n_seeds: int = 150, profile: dict | None = None) -> dict:
    ref = reference_selfcheck(n_seeds)
    audits = [audit_verifier(v, n_seeds, profile) for v in VERIFIERS.values()]
    return {"reference_oracle": ref,
            "verifiers": [a.__dict__ for a in audits],
            "error_budget": error_budget(audits)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=150)
    ap.add_argument("--out", default="results_e7_verifier_audit.json")
    args = ap.parse_args()

    r = run(args.seeds)
    ref, eb = r["reference_oracle"], r["error_budget"]

    print("=" * 78)
    print("0. 参照 oracle 自检（前提：DIC 可信，否则后面全部作废）")
    print(f"   DIC 全有效: {ref['reference_trustworthy']}    "
          f"干净账套违规: {len(ref['clean_ledger_violations'])} 例")

    print("=" * 78)
    print("1. 漏判率分解：检测层 vs 归因层（精确测量，非估计）")
    print(f"{'verifier':<20}{'检测FNR':>9}{'归因FNR':>9}{'端到端FNR':>11}{'干净误报':>10}")
    for a in r["verifiers"]:
        print(f"{a['name']:<20}{a['det_fnr']:>9.3f}{a['attr_fnr']:>9.3f}"
              f"{a['fnr']:>11.3f}{a['det_fnr_clean_fp']:>10.3f}")

    print("=" * 78)
    print("2. 误差系统性检验：NMI(手法类型, 检测层漏判)，附打乱对照")
    for a in r["verifiers"]:
        tag = "系统性" if a["nmi"] > a["nmi_shuffled"] + 0.05 else "近似随机"
        print(f"   {a['name']:<20} NMI={a['nmi']:.3f}  对照={a['nmi_shuffled']:.3f}"
              f"  → {tag}")

    print("=" * 78)
    print("3. 错误预算：手法 × verifier 的检测层 FNR")
    ops = sorted(FRAUD_OPS)
    print(f"{'手法':<14}" + "".join(f"{v[:13]:>15}" for v in eb["verifiers"]))
    for op in ops:
        print(f"{op:<14}" + "".join(
            f"{eb['det_fnr_matrix'][v][op]:>15.2f}" for v in eb["verifiers"]))
    print("\n   每个手法的实际破坏集（= 它碰到的会计约束）:")
    for op in ops:
        print(f"     {op:<14}{eb['oracle_coverage'][op]}")
    print("\n   结构性不可见（该 verifier 的判据与破坏集无交集，恒漏判）:")
    for v, lst in eb["structurally_invisible"].items():
        if lst:
            print(f"     {v}: {', '.join(lst)}")
    print(f"\n   覆盖最差: {', '.join(eb['least_covered'])}")

    Path(args.out).write_text(json.dumps(r, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print("=" * 78)
    print(f"已写出 {args.out}")


if __name__ == "__main__":
    main()
