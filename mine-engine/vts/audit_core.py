"""审计域 VTS 最小核心：复式记账 oracle + 舞弊注入 + 差分隔离证书。

设计原则
--------
1. **oracle 是领域先验，先于任务存在**，因此可跨题复用 —— 这是 C 类可验证性。
2. 明细账（vouchers）与报表（reported）是两个对象；
   舞弊 = 只改报表、不改明细（或反之），这正是审计要发现的现象。
3. 恒等式作用于**结转后**的报表，这是会计准则的真实口径。

本文件零第三方依赖，可独立运行核验。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- 科目表

ASSETS = {"1001_cash", "1002_bank", "1122_ar", "1403_material", "1601_fa"}
CONTRA_ASSETS = {"1602_accum_dep"}
LIABILITIES = {"2202_ap", "2211_payroll"}
EQUITY = {"4001_capital"}
REVENUE = {"6001_revenue"}
EXPENSES = {"6601_selling", "6602_admin", "6801_tax_expense"}
TEMP = REVENUE | EXPENSES
ALL = (ASSETS | CONTRA_ASSETS | LIABILITIES | EQUITY
       | REVENUE | EXPENSES | {"1001_cash"})

ACCOUNTS = sorted(ALL)

# 会计政策参数（真实准则区间，oracle 依此判定）
POLICY = {
    "depreciation_rate_range": (0.03, 0.10),   # 年折旧率
    "bad_debt_rate": 0.05,                     # 应收账款坏账准备计提率
}

# `make_seed_ledger` 里 n_periods=4 对应"一年四个季度"，
# 但**基准折旧率 0.05 是年率**，故单期应计提 = 原价 × 0.05 / 4。
# ⚠️ 这个换算系数是实测得来（见 28 号文档）：
#    种子账套每期累计折旧率恰为 0.0125 = 0.05/4。
#    若将来把 `n_periods` 改成非季度粒度，此处必须同步改。
N_PERIODS_PER_YEAR = 4

# `o_accum_dep` 的宽松系数：本期至少应计提上期累计折旧的
# DEPR_MIN_RATIO 倍。要求"本期累计 ≥ 上期累计 + required"。
# ⚠️ 设计参数，非实测标定值；A0 前必须过验收矩阵（不恒真也不恒假）。
DEPR_MIN_RATIO = 0.5

# `o_cutoff_period` 的容差：本期应收增量允许超出本期收入发生额的比例。
# 现实中存在信用销售/赊销尾款，故允许一定超出；超出部分即"无收入支撑的应收"。
# ⚠️ 设计参数。实测标定：干净账套各期 ar_flow 均 ≤ rev_flow，无需容差；
#    `op_cutoff` 注入后 ar_flow 达1.02e6 而 rev_flow≈1.03e6，
#    ⚠️ **注意：op_cutoff 注入的 amt 恰好接近收入量级，单靠量级可能判不出来**，
#    该项正在验收中（见 28 号文档 §3.2 的诚实说明）。
AR_OVER_REV_TOL = 0.20


@dataclass
class Voucher:
    eid: str
    period: int
    debit: str
    credit: str
    amount: float


@dataclass
class Ledger:
    """账套 = 凭证流 + 期初余额 + 结转后的报表。

    expected[p]  : 由期初 + 凭证推导的**未结转**余额（明细账口径）
    reported[p]  : 报表上的期末数（结转后口径，损益已并入权益）
    """
    opening: dict[str, float]
    vouchers: list[Voucher] = field(default_factory=list)
    reported: dict[int, dict[str, float]] = field(default_factory=dict)
    n_periods: int = 4

    def clone(self) -> "Ledger":
        return copy.deepcopy(self)


# ---------------------------------------------------------------- 明细推导

def period_flow(led: Ledger, period: int, acct: str) -> float:
    """期间发生额，按科目**正常余额方向**归一。

    资产/费用：借方为正（借方 - 贷方）
    负债/权益/收入：贷方为正（贷方 - 借方）
    收入取负值，使「资产 = 负债 + 权益 + 收入 - 费用」直接可算。
    """
    debit = credit = 0.0
    for v in led.vouchers:
        if v.period != period:
            continue
        if v.debit == acct:
            debit += v.amount
        if v.credit == acct:
            credit += v.amount
    debit, credit = round(debit, 2), round(credit, 2)
    if acct in LIABILITIES or acct in EQUITY:
        return round(credit - debit, 2)
    if acct in REVENUE:
        return round(-(credit - debit), 2)   # 收入记为负
    return round(debit - credit, 2)


def expected_detail(led: Ledger, period: int) -> dict[str, float]:
    """未结转的明细账余额（审计底稿口径）。"""
    bal = dict(led.opening)
    for p in range(1, period + 1):
        for a in ACCOUNTS:
            bal[a] = round(bal.get(a, 0.0) + period_flow(led, p, a), 2)
    return {k: round(v, 2) for k, v in bal.items()}


def expected_reported(led: Ledger, period: int) -> dict[str, float]:
    """结转后的报表数：损益归零，净损益并入权益。

    口径说明（期初余额也按同一方向归一）：
    - 资产/费用：正数为借方余额
    - 负债/权益：正数为贷方余额
    - 收入：负数（贷方发生额取负），因此净损益 = 收入 - 费用 = -(sum) - sum(费用)
    """
    det = expected_detail(led, period)
    row = dict(det)
    revenue = sum(det.get(a, 0.0) for a in REVENUE)     # 负数
    expense = sum(det.get(a, 0.0) for a in EXPENSES)     # 正数
    net = -(revenue + expense)                           # 净利润（可能为负）
    for a in TEMP:
        row[a] = 0.0
    row["4001_capital"] = round(row.get("4001_capital", 0.0) + net, 2)
    return {k: round(v, 2) for k, v in row.items()}


# ---------------------------------------------------------------- Oracle
# 全部作用于「结转后报表」口径，与真实会计准则一致。

def o_equation(led: Ledger, period: int) -> bool:
    """O1 会计恒等式：资产 - 抵减项 = 负债 + 所有者权益。

    这是审计最核心的一条，审稿人可自行查准则。
    """
    rep = led.reported.get(period, {})
    assets = sum(rep.get(a, 0.0) for a in ASSETS) + sum(
        rep.get(a, 0.0) for a in CONTRA_ASSETS)
    rhs = sum(rep.get(a, 0.0) for a in LIABILITIES) + sum(
        rep.get(a, 0.0) for a in EQUITY)
    return abs(assets - rhs) <= 0.01


def o_tie_detail(led: Ledger, period: int) -> bool:
    """O2 报表 = 明细账结转后（表账一致）。"""
    exp = expected_reported(led, period)
    rep = led.reported.get(period, {})
    for a in ACCOUNTS:
        if abs(rep.get(a, 0.0) - exp.get(a, 0.0)) > 0.01:
            return False
    return True


def o_rollforward(led: Ledger, period: int) -> bool:
    """O3 递推：报表期末 = 报表上期期末 + 本期发生额（结转前科目）。"""
    if period <= 1:
        return True
    prev = led.reported.get(period - 1, {})
    cur = led.reported.get(period, {})
    for a in (ASSETS | CONTRA_ASSETS | LIABILITIES):
        exp = round(prev.get(a, 0.0) + period_flow(led, period, a), 2)
        if abs(cur.get(a, 0.0) - exp) > 0.01:
            return False
    return True


def o_policy(led: Ledger, period: int) -> bool:
    """O4 会计政策：累计折旧率不得超过准则上限（累计口径，随期数单调增长）。

    ⚠️ **本函数是死代码，实测已确认**（见 `28-A0前置诊断与方案迭代v5.md` §2.1）：
    - 只判**上限**，而种子账套累计折旧率实测区间仅 0.0125–0.0500，
      阈值 `POLICY["depreciation_rate_range"][1]` = 0.10 **永不可达**；
    - 200 seed × 4 期 = 800 个样本，`o_policy` 判假 **0** 次；
    - 更根本的是方向反了：`op_depreciation` 做的是**少提折旧**（累计折旧率被调低），
      而本函数只在**超上限**时报警 ⇒ 结构上不可能抓到它。

    ⇒ **保留它仅为了记录"上限"这一侧的历史语义；真正的折旧不足检测器是 `o_accum_dep`。**
    新增 `op_dep_over`（超额计提）才可能触发本函数。
    """
    rep = led.reported.get(period, {})
    fa = rep.get("1601_fa", 0.0)
    dep = abs(rep.get("1602_accum_dep", 0.0))
    if fa > 0:
        _, hi = POLICY["depreciation_rate_range"]
        if dep / fa > hi + 1e-6:
            return False
    return True


def o_accum_dep(led: Ledger, period: int) -> bool:
    """O5 累计折旧合理性：**按期计提下限**判定（对应"折旧计提不足"）。

    为什么必须有下限（这是§2.1 诊断的核心修复）
    ------------------------------------------------
    会计上：累计折旧率**偏低** ⇒ 折旧计提不足 ⇒ 折旧少计 ⇒ 利润虚增。
    `o_policy` 只判上限 ⇒ 对"折旧不足"这一最常见舞弊**完全失明**，
    而 `op_depreciation` 注入的正是折旧不足。

    ⚠️ **固定阈值法在本题上被实测否掉（保留记录，勿重犯）**
    最初按 `floor = min(r_stable, p × r_stable) × κ`（κ=0.5）设下限，
    实测**误报 150/600**（每个 seed 第 1 期全FAIL）。
    根因：种子账套实际年折旧率是 **0.05**（每期 0.0125），
    而政策区间下界 `r_stable` = **0.03**，两者不一致——
    p=1 时 floor = 0.015 > 干净值 0.0125 ⇒ 假阳性。

    ⚠️ 更致命的是：干净值 0.0125 与 `op_depreciation` 注入后的 **0.0100**
    仅差 **0.0025**。任何固定阈值都极易把二者判反——
    **累计折旧率这个总量指标分辨力不足**。
    ⇒ 改为**逐期相对判据**。

    改用的判据
    ----------
        本期累计折旧 ≥ 前一期累计折旧 + 本期应计提折旧

    理由：折旧是**逐期计提**的。若某期累计折旧相对上期几乎没增长，
    即"这一期基本没提"，无论绝对水平如何都可疑。
    该判据只依赖**相邻两期之差**，与账套的绝对折旧率无关，
    因此不会因种子账套参数而假阳性。
    """
    if period <= 1:
        return True
    rep = led.reported.get(period, {})
    prev = led.reported.get(period - 1, {})

    cur_dep = abs(rep.get("1602_accum_dep", 0.0))
    prev_dep = abs(prev.get("1602_accum_dep", 0.0))
    fa = rep.get("1601_fa", 0.0)
    if fa <= 0:
        return True

    r_stable, _ = POLICY["depreciation_rate_range"]
    # 单期应计提折旧 = 原价 ×（年折旧率下界 / 每期期数）
    required = fa * (r_stable / N_PERIODS_PER_YEAR) * DEPR_MIN_RATIO
    return cur_dep >= prev_dep + required - 0.01


def o_cutoff_period(led: Ledger, period: int) -> bool:
    """O6 认定级检测：**按科目分组的表账偏离** —— 应收账款（针对 `op_cutoff`）。

    为什么需要它
    ------------
    `op_cutoff`（跨期调节）与 `op_capitalize`（费用资本化）、
    `op_offbook`（账外账）的违反签名**完全相同**（都是"资产与权益同增"型），
    ⇒ 参照层无法区分这三条**不同审计认定**。

    ⚠️ **两次被实测否掉的设计（保留记录，勿重犯）**
    - 第 1 版"收入下降但应收未动" ⇒ **零触发**。根因：`6001_revenue`在
      **结转后报表里恒为 0**（`expected_reported` 清零全部 TEMP 科目），
      判据第一条腿立不起来。**任何基于结转后科目余额的判据都不可用。**
    - 第 2 版"用 `period_flow` 比较应收增量与收入发生额" ⇒ **0/80 全漏**。
      根因更根本：**所有注入算子只改 `reported`，从不改 `vouchers`**，
      而 `period_flow` 读明细账 ⇒ 注入在它眼里根本不存在。

    ⇒ 唯一可用数据源是**报表值与明细账推出值的偏离**
    （`reported` vs `expected_reported`），这也正是 `o_tie_detail` 用的量。
    但 `o_tie_detail` 是**全科目一次性比较** ⇒ 只知"有偏离"、不知"哪个科目偏离"，
    因此对认定不敏感。本oracle 把同一判据**按科目拆开**，给出认定级信号。

    科目组：`1122_ar`（应收账款）⇒ 流动资产认定。
    """
    exp = expected_reported(led, period)
    rep = led.reported.get(period, {})
    gap = abs(rep.get("1122_ar", 0.0) - exp.get("1122_ar", 0.0))
    return gap <= 0.01


def o_classification(led: Ledger, period: int) -> bool:
    """O7 认定级检测：**按科目分组的表账偏离** —— 固定资产（针对 `op_capitalize`）。

    针对 `op_capitalize`（费用转资产）：资产与权益同增，会计上合法，
    但改变的是**列报分类**。它与 `offbook`/`cutoff` 违反签名相同，无法区分。

    ⚠️ **一次被实测否掉的设计（保留记录，勿重犯）**
    初版"结转后费用科目仍有余额 ⇒ 判假"，实测**零触发且逻辑错误**：
    干净账套的 `expected_reported` 同样清零费用科目（实测各期恒为 0.0），
    而 `op_capitalize` 也只加固定资产、不加费用科目 ⇒ 两头都不成立。

    ⇒ 同样改用**按科目分组的表账偏离**：科目组 `1601_fa`（固定资产原值），
    属长期资产认定。与 `o_cutoff_period` 的应收组**互不重叠**，
    二者可同时触发 ⇒ 签名空间才够分。
    """
    exp = expected_reported(led, period)
    rep = led.reported.get(period, {})
    gap = abs(rep.get("1601_fa", 0.0) - exp.get("1601_fa", 0.0))
    return gap <= 0.01



ORACLES: dict[str, Callable[[Ledger, int], bool]] = {
    "o_equation": o_equation,
    "o_tie_detail": o_tie_detail,
    "o_rollforward": o_rollforward,
    "o_policy": o_policy,
    "o_accum_dep": o_accum_dep,
    "o_cutoff_period": o_cutoff_period,
    "o_classification": o_classification,
}


# ---------------------------------------------------------------- 舞弊算子
# 全部只改报表、不改明细账 —— 这正是审计要发现的现象。

@dataclass
class FraudOp:
    name: str
    fraud_type: str
    expects: set[str]
    apply: Callable[[Ledger, dict], None]


def _amt(led: Ledger, period: int) -> float:
    """取一个有界的金额：不超过期初固定资产原值，避免注入金额与账套量级脱节。"""
    fa = abs(led.opening.get("1601_fa", 0.0)) or 1.0
    return round(fa * 0.05, 2)


def op_offbook(led: Ledger, theta: dict) -> None:
    """账外账：报表多出一笔收入与银行存款，明细账完全没有。"""
    p = led.n_periods
    amt = theta.get("amount") or _amt(led, p)
    rep = led.reported[p]
    rep["1002_bank"] = round(rep.get("1002_bank", 0.0) + amt, 2)
    rep["4001_capital"] = round(rep.get("4001_capital", 0.0) + amt, 2)


def op_cutoff(led: Ledger, theta: dict) -> None:
    """跨期调节（销售收入跨期确认）：把本期应收提前确认为收入。

    会计上正确的做法是：收入已确认但现金未收 —— 恒等式仍然成立。
    舞弊在于**报表口径**把这笔收入挪到了不该确认的期间，
    表现为「本期权益被调高、但明细账的本期发生额不支持」。
    """
    p = led.n_periods
    amt = theta.get("amount") or _amt(led, p)
    rep = led.reported[p]
    rep["1122_ar"] = round(rep.get("1122_ar", 0.0) + amt, 2)   # 资产：提前确认应收
    rep["4001_capital"] = round(rep.get("4001_capital", 0.0) + amt, 2)


def op_depreciation(led: Ledger, theta: dict) -> None:
    """折旧计提不足：把累计折旧调低（少提折旧 = 虚增利润）。"""
    p = led.n_periods
    fa = led.reported[p].get("1601_fa", 0.0)
    cut = theta.get("amount") or fa * 0.04      # 少提 4 个百分点
    rep = led.reported[p]
    rep["1602_accum_dep"] = round(rep.get("1602_accum_dep", 0.0) + cut, 2)
    rep["4001_capital"] = round(rep.get("4001_capital", 0.0) + cut, 2)


def op_capitalize(led: Ledger, theta: dict) -> None:
    """费用资本化：费用转资产，利润虚增。"""
    p = led.n_periods
    amt = theta.get("amount") or _amt(led, p)
    rep = led.reported[p]
    rep["1601_fa"] = round(rep.get("1601_fa", 0.0) + amt, 2)
    rep["4001_capital"] = round(rep.get("4001_capital", 0.0) + amt, 2)


def op_capitalize_keep_dep(led: Ledger, theta: dict) -> None:
    """资产虚增但不动折旧计提 → 同时破恒等式与政策（复合手法）。"""
    op_capitalize(led, theta)


def op_equation_break(led: Ledger, theta: dict) -> None:
    """🔴 异增型注入（恒等式破坏型）—— 只动资产一侧，不冲权益。

    与其余四个算子的关键区别
    ----------------------
    其余算子全是"资产 +X、权益/权益 +X"的**同增型**注入，
    在会计上是合法的（资产与权益同增不破坏恒等式），
    所以 `o_equation` 在它们身上**永远不会触发**（实测 0 次）。

    本算子只虚增资产、不动权益 ⇒ 会计恒等式必然失衡，
    `o_equation` 得以真正参与判别。

    ⚠️ **定位声明（重要，不要拿它当主难度档）**
    这在会计上更接近"**明显错误**"而非"**隐蔽舞弊**"，难度偏低。
    它的作用是验证**参照层的完备性**——
    即"最核心、最容易被审稿人独立验证的一条约束确实在工作"。
    论文中不作为主难度档，只作参照层自检。
    """
    p = led.n_periods
    amt = theta.get("amount") or _amt(led, p)
    rep = led.reported[p]
    # 只动资产，不动 4001_capital ⇒ 恒等式差 = +amt
    rep["1601_fa"] = round(rep.get("1601_fa", 0.0) + amt, 2)


def op_dep_over(led: Ledger, theta: dict) -> None:
    """超额计提折旧（累计折旧率超上限）—— 唯一可能触发 `o_policy` 的注入。

    会计上属"激进折旧节税"，与"折旧不足虚增利润"方向相反，
    故**只用于让 `o_policy` 这条上限约束有被测试的机会**，
    不属于主难度档。
    """
    p = led.n_periods
    rep = led.reported[p]
    fa = rep.get("1601_fa", 0.0)
    hi = POLICY["depreciation_rate_range"][1]
    target = fa * hi * 1.5                     # 超过上限 50%
    cur = abs(rep.get("1602_accum_dep", 0.0))
    delta = round(target - cur, 2)
    rep["1602_accum_dep"] = round(rep.get("1602_accum_dep", 0.0) - delta, 2)
    # 累计折旧增加 ⇒ 权益同减（折旧计入费用）
    rep["4001_capital"] = round(rep.get("4001_capital", 0.0) - delta, 2)


# 声明值全部来自 DIC 实测（50 seed），不是主观假定。
#
# 实测得出的三条领域事实（重要，写进 paper 的方法节）：
#
# 1. **改报表期末数必然连带破坏 `o_tie_detail` 与 `o_rollforward`**。
#    所以"每个手法恰好破坏一条 oracle"在会计域不成立，
#    判据必须是「无意外项 + 核心项确实被破坏」，而不是集合相等。
#
# 2. **费用资本化与折旧不足在会计上并不破坏会计恒等式** ——
#    资产与权益同增，恒等式仍然成立（差 = 0，实测确认）。
#    它们破坏的是「表账一致」：明细账里费用还在，报表上却记进了资产。
#    → 这是一个反直觉但正确的结论，也是 C 类 oracle 的价值所在：
#       **判据必须是会计意义上的约束，而不是"看起来不平衡"。**
#
# 3. 🔴 **2026-10-05 新增（见 28 号文档）**：
#    上述 2 条合起来导致一个**参照层无分辨力**的后果——
#    四个主算子违反的 oracle 集合**完全相同**，从参照层看四条不同审计认定
#    （completeness / cutoff / valuation / presentation）**不可区分**，
#    "四档难度"被压平成一档。
#    ⇒ 因此新增三条**按认定敏感**的 oracle：
#       `o_accum_dep`（valuation，含下限，修`o_policy` 死代码）、
#       `o_cutoff_period`（cutoff）、`o_classification`（presentation）。
#    并新增两个**非主难度档**算子让 `o_equation` 与 `o_policy` 真正有被测机会：
#       `equation_break`（异增型，恒等式自检）、`dep_over`（超额折旧，上限自检）。
FRAUD_OPS: dict[str, FraudOp] = {
    "offbook": FraudOp("offbook", "账外账/体外循环",
                       {"o_tie_detail", "o_rollforward"}, op_offbook),
    "cutoff": FraudOp("cutoff", "跨期调节",
                      {"o_tie_detail", "o_rollforward", "o_cutoff_period"},
                      op_cutoff),
    "depreciation": FraudOp("depreciation", "折旧计提不足",
                            {"o_tie_detail", "o_rollforward", "o_accum_dep"},
                            op_depreciation),
    "capitalize": FraudOp("capitalize", "费用资本化",
                          {"o_tie_detail", "o_rollforward", "o_classification"},
                          op_capitalize),
    # 非主难度档：参照层完备性自检
    "equation_break": FraudOp(
        "equation_break", "恒等式破坏（异增型，自检）",
        {"o_equation", "o_tie_detail", "o_rollforward", "o_classification"},
        op_equation_break),
    "dep_over": FraudOp(
        "dep_over", "超额计提折旧（上限自检）",
        {"o_policy", "o_tie_detail", "o_rollforward"},
        op_dep_over),
}


# ---------------------------------------------------------------- 差分隔离证书

@dataclass
class DIC:
    trial_id: str
    operator: str
    violated: list[str]      # 实际被破坏的 oracle
    expected: list[str]      # 算子声明应被破坏的 oracle
    unexpected: list[str]    # 声明外也被破坏的（连带，合法）
    missing: list[str]       # 声明了但没破坏的（注入无效）
    no_unexpected: bool      # 隔离性：无意外破坏
    effective: bool          # 有效性：核心项确实被破坏

    @property
    def valid(self) -> bool:
        return self.no_unexpected and self.effective


def certify(led: Ledger, op_name: str, theta: dict, trial_id: str) -> DIC:
    """核验差分隔离证书：注入前后各跑一遍 oracle，比对差异集合。

    判据（经实测修正）
    ------------------
    最初设想「每个算子恰好破坏一条 oracle」，但在会计域**不成立**：
    实测发现改动报表期末数必然同时破坏 `o_tie_detail`（表账一致）与
    `o_rollforward`（递推），只有当改动同时落在资产与权益两侧时才额外破坏
    `o_equation`。因此正确判据是：

        unexpected = violated - declared   （不能有意外项）
        missing    = declared - violated   （核心项必须真的被破坏）

    - `no_unexpected`：无意外破坏（**隔离性**）
    - `effective`：核心项确实被破坏（**有效性**）

    这两个条件合起来才是"这次注入的破坏是可预期的"。
    纯函数、毫秒级、审稿人可自行复现 —— 这是 C 类与 A 类
    （LLM 派生的 reward function）的核心差异。
    """
    op = FRAUD_OPS[op_name]
    injected = led.clone()
    op.apply(injected, theta)
    p = led.n_periods

    violated = set(n for n, fn in ORACLES.items()
                   if fn(led, p) and not fn(injected, p))
    declared = set(op.expects)
    unexpected = violated - declared
    missing = declared - violated

    return DIC(
        trial_id=trial_id,
        operator=op_name,
        violated=sorted(violated),
        expected=sorted(declared),
        unexpected=sorted(unexpected),
        missing=sorted(missing),
        no_unexpected=not unexpected,
        effective=not missing,
    )


# ---------------------------------------------------------------- 种子账套生成

def make_seed_ledger(seed: int) -> Ledger:
    """生成一份**天然满足全部 oracle** 的合法账套。

    关键：凭证集必须是真正的复式记账，且报表按结转后口径生成。
    """
    import random
    rng = random.Random(seed)

    opening = {a: 0.0 for a in ACCOUNTS}
    fa0 = round(rng.uniform(2e6, 2e7), 2)
    opening["1601_fa"] = fa0
    opening["4001_capital"] = fa0          # 实收资本 = 固定资产原值（贷方正数）
    opening["1002_bank"] = round(rng.uniform(1e5, 1e6), 2)
    opening["4001_capital"] = round(
        opening["4001_capital"] + opening["1002_bank"], 2)

    led = Ledger(opening=opening, n_periods=4)
    dep_rate = 0.05
    n = 0
    for p in range(1, 5):
        n += 1
        sale = round(rng.uniform(1e5, 2e6), 2)
        collect = round(sale * rng.uniform(0.6, 1.0), 2)
        buy = round(rng.uniform(5e4, 8e5), 2)
        used = round(buy * rng.uniform(0.3, 0.6), 2)
        dep = round(fa0 * dep_rate / 4, 2)
        salary = round(rng.uniform(2e4, 1e5), 2)

        led.vouchers += [
            Voucher(f"V{n:03d}P{p}s", p, "1122_ar", "6001_revenue", sale),
            Voucher(f"V{n:03d}P{p}c", p, "1002_bank", "1122_ar", collect),
            Voucher(f"V{n:03d}P{p}b", p, "1403_material", "1002_bank", buy),
            Voucher(f"V{n:03d}P{p}u", p, "6602_admin", "1403_material", used),
            Voucher(f"V{n:03d}P{p}d", p, "6602_admin", "1602_accum_dep", dep),
            Voucher(f"V{n:03d}P{p}w", p, "6601_selling", "2211_payroll", salary),
        ]
        led.reported[p] = expected_reported(led, p)
    return led
