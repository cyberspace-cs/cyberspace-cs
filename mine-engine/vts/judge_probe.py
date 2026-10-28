"""S1：真实 LLM judge 的漏判率 / 误报率实测（本项目的 go-no-go 闸门）。

=====================================================================
为什么这是整个 v4 方向的第一道闸门
=====================================================================
v4 的全部叙事建立在"judge（判分器）本身是不可靠的，而且它的错误是系统性的"，
并进一步主张"这种系统性误差会让 RLVR/GRPO 悄悄训歪"。

但**至今所有 FNR 数字都来自 verifier_audit.py 里的 `profile` 参数**——
那是我们自己写死的"模型会给哪类答案"的分布，不是测出来的。
换句话说：我们一直在用假设去论证假设。

本模块是第一次拿真实模型去测这个假设。若真实 judge 的漏判率其实很低，
那么"必须审计 verifier"这件事的紧迫性就没了，方向应当立刻转向。
所以这不是补充实验，是**决定要不要继续做这个方向的实验**。

=====================================================================
决策规则（在跑之前写死，不许事后改口）
=====================================================================
设 `FNR*` = **最宽松配置下**（Arm C：给足算术、给足程序清单、给足类型标签）
                真实 judge 的**端到端漏判率**。

    FNR* >= 0.20  →  叙事成立，继续做（并把"verifier 需要程序化覆盖"写成结论）
    FNR* <  0.20  →  叙事失去张力，**转向**

取"最宽松配置"而不是平均，是**对我们不利的一侧**：
如果连我们主动帮它减负、明确告诉它该做哪些审计程序之后它都还能漏，
那"真实审计里的 judge 更差"就成立；反过来如果这样都漏判率很低，
就没有理由相信"judge 不可靠"这个前提。这一侧的选择不能事后改成对自己有利的。

用端到端（既要求检出、又要求说对手法类型）而不是仅检测层，
同样是取不利的一侧：仅检测层 FNR 几乎必然更低。

=====================================================================
实验设计：三个 arm 的差别只在"我们帮它多少"（对抗自己）
=====================================================================
审计题对 LLM 有一个致命的混淆因素——**它不会算账**。
24 张凭证、4 个期间、16 个科目，让模型在上下文里自己加总，
测出来的 FNR 可能只是"加法不行"，而不是"审计语义不行"。
这两者被混在一起，本模块的结论就没有意义。

所以 arm 是**帮它减负的梯度**，用来把"算术失败"从"判断失败"里剥出来：

  Arm A  naive      原始账套（凭证 + 各期报表），开放式提问，不给任何提示
  Arm B  workpaper  已算好逐科目逐期借贷发生额（**消掉求和**），仍不给差异
  Arm C  checklist  workpaper + 显式列出应执行的审计程序 + 给定手法标签闭集

三个口径的 FNR 之差就是"判据覆盖"带来的收益：
- 若 FNR(A) >> FNR(C)：真实原因是 **verifier 没跑那条程序**，
  结论应写成"判分器的覆盖依赖于它碰巧做了什么"，而不是"LLM 不懂会计"。
- 若 FNR(C) 仍高：结论更硬（执行层面也不稳）。
- 若 FNR(C) 已 < 0.2：闸门关闭，转向。

**注意 Arm C 里列出的程序覆盖全部 4 种手法（对称）**，不针对任何一个具体样本，
所以它不是答案泄漏；干净账套那一组同时也在测"给了程序清单会不会过度报警"。

=====================================================================
两层漏判率（沿用 verifier_audit.py 的分层，理由相同）
=====================================================================
    检测层  judged "有问题吗" 错→ 漏
    归因层  已检出但手法类型说错 → 错
    端到端  两者都对才算判对    → 决策指标

=====================================================================
三条工程纪律（都是被坑过的）
=====================================================================
1. **空答案不算漏判**。thinking 模型会先烧光token 再作答，max_tokens 不够时
   返回 HTTP 200 + 空字符串。从外面看"正常运行"，实际是被吞掉的样本。
   空答案/ 解析失败**单列**，不进FNR 分母。否则会把基础设施故障
   伪装成"LLM 判分能力差"，这是最不可辩护的一类错误。
2. **裁判必须真跑自己的 oracle**。judge 的判定来自它自己的输出，
   真值来自 DIC；两者独立。任何一处不自检，整批数据作废。
3. **响应落 JSONL 且可续跑**。这是付费调用，跑到 2900/3000 断线不能重头再来。
"""

from __future__ import annotations

import json
import os
import re
import statistics
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from vts.audit_core import FRAUD_OPS, certify, make_seed_ledger

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 统计工具

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 区间。

    为什么必须给区间而不是只给点估计：go/no-go 的阈值是 0.20，
    而 n=100 时观测 0.18 的 95% 区间上界是0.27——分不开就没有结论。
    报点估计等于把噪声当信号。
    """
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n) + z * z / (4 * n * n)) ** 0.5
    return (round((c - m) / d, 4), round((c + m) / d, 4))


# ---------------------------------------------------------------- 账套渲染

_SIGNS = """
科目方向与结转口径（审计底稿通用约定，请严格按此判断）：
- 资产类(1001/1002/1122/1403/1601)：借方为正。
- 累计折旧(1602) 为贷方余额，报表上以**负数**列示，是资产的抵减项。
- 负债类(2202/2211)、所有者权益(4001)：贷方为正。
- 收入类(6001)：贷方为正，本模块统一取**负号**表示。
- 费用类(6601/6602/6801)：借方为正。
- 结转规则：期末把损益类科目(6001/6601/6602/6801)全部结转为 0，
  净损益 = 收入 - 费用（即 -(收入合计) - 费用合计），加计到 4001 所有者权益。

【会计期间与折旧口径（重要，否则你会被误导）】
- 本账套的 P1~P4 是**同一个会计年度内的 4 个季度**，P4 期末 = 年末。
- 因此「累计折旧 / 固定资产原值」应当落在**年度**折旧率区间内，
  而**不是**随期数累加到 4 倍。年折旧率区间：3% ~ 10%。
- 例：原值 1000万、全年按 5% 计提，则 P4 的累计折旧应为 50万（比率 5%），
  这是**正常**的，不是折旧计提不足。
- 只有当 P4 的 累计折旧/原值 **低于 3%**（计提不足）或**高于 10%**（计提过度）
  才构成折旧政策问题。注意收入/费用类科目结转后为 0 属正常，不要当成异常。

【权责发生制（最容易误报的地方，务必读完）】
- 本账套采用**权责发生制**，不是收付实现制。
- **「收入已确认但现金尚未收到」是正常的**，不是跨期调节（cutoff）。
  销售确认收入的同时挂应收账款，收款发生在后续期间，两期金额本来就不相等。
  只有当收入被记在**错误的会计期间**（如本期发货却提前确认到上期，
  或本期已确认却漏记）时，才构成 cutoff 问题。
- 判断 cutoff 要看**收入的确认期间是否与发货/提供劳务的期间一致**，
  而不是「本期收款是否等于本期收入」。后者在权责发生制下必然不等。
- 材料采购尚未领用（存货挂账）属正常；只有成本已发生却长期挂存货
  才需要关注，这不属于本题要求的四类手法。
""".strip()


def _f(x: float) -> str:
    return f"{x:,.2f}"


def render_raw(led) -> str:
    """Arm A：原始凭证 + 各期报表。不做任何预计算。"""
    lines = ["【明细账：记账凭证】",
             "凭证号 | 期间 | 借方科目 | 贷方科目 | 金额"]
    for v in led.vouchers:
        lines.append(f"{v.eid} | P{v.period} | {v.debit} | {v.credit} | {_f(v.amount)}")
    lines += ["", "【期初余额】"]
    for a, x in sorted(led.opening.items()):
        if x:
            lines.append(f"{a} | {_f(x)}")
    lines += ["", "【各期报表期末数（已结转损益）】"]
    for p in sorted(led.reported):
        lines.append(f"--- P{p} ---")
        for a, x in sorted(led.reported[p].items()):
            if x:
                lines.append(f"{a} | {_f(x)}")
    return "\n".join(lines)


def _debit_credit(led, p: int, acct: str) -> tuple[float, float]:
    d = c = 0.0
    for v in led.vouchers:
        if v.period != p:
            continue
        if v.debit == acct:
            d += v.amount
        if v.credit == acct:
            c += v.amount
    return round(d, 2), round(c, 2)


def render_workpaper(led) -> str:
    """Arm B/C：**预求和**的"科目发生额及余额表"。

    只帮忙把"逐张凭证加总"这一步算掉；**跨期递推与结转仍留给 judge 判断**。
    刻意**不**给出「应有期末 vs 报表期末」的差异列——那等于直接给答案。

    两条必须做对的地方，都是自查时发现的坑：

    1. **零值必须显式写成 0.00，不能写成 `-`。**
       结转后损益类科目期末就是 0，第一版渲染成 `-`，judge 无法区分
       "这本是0"和"这里没给数据"。这个歧义会**双向污染测量**：
       读成缺数据→ 误报（虚高FPR）；读成 0→ 可能漏掉真实的 0 值异常。
       测FPR 的样本里必须没有歧义，否则测出来的误报率不可解释。
    2. **每一期都要给自己的期初余额**（= 上期期末的明细口径余额），
       否则 judge 做不了第2 期起的递推核对 —— 那会让 arm B/C 因为
       "题面缺数据"而变难，测出来的 FNR 混进了出题失误，不是模型能力。
    """
    from vts.audit_core import ACCOUNTS, expected_detail
    periods = sorted(led.reported)
    lines = ["【科目发生额及余额表（借贷发生额已加总；期初余额与各期报表期末数仍需你自行勾稽）】",
             "科目 | 期初余额 | 本期借方发生额 | 本期贷方发生额 | 报表期末数（结转后）"]

    prev_detail = None
    for p in periods:
        if p == periods[0]:
            opening_row = {a: led.opening.get(a, 0.0) for a in ACCOUNTS}
        else:
            opening_row = prev_detail          # 上期期末的明细口径 = 本期期初
        lines.append(f"--- P{p} ---")
        for a in ACCOUNTS:
            d, c = _debit_credit(led, p, a)
            op = round(opening_row.get(a, 0.0), 2)
            rep = round(led.reported[p].get(a, 0.0), 2)
            # 全零且无发生额的科目不列，避免噪声；但只要任一非零就必须列出，
            # 且四个金额列一律显式给数字（0.00 也给），不给 '-'
            if not (d or c or op or rep):
                continue
            lines.append(f"{a} | {_f(op)} | {_f(d)} | {_f(c)} | {_f(rep)}")
        prev_detail = expected_detail(led, p)

    lines += ["", "【各期报表明细（损益已结转；累计折旧以负数列示）】"]
    for p in periods:
        lines.append(f"--- P{p} ---")
        for a in ACCOUNTS:
            rep = round(led.reported[p].get(a, 0.0), 2)
            if rep:
                lines.append(f"{a} | {_f(rep)}")
    return "\n".join(lines)


CHECKLIST = """
【你必须逐项执行的审计程序（这是本次复核的工作底稿清单，不许跳项）】
P1 勾稽核对：由凭证明细逐科目推算的期末余额，是否与报表列示的期末数一致。
P2 递推核对：本期报表期末数，是否等于上期期末数加本期发生额。
P3 会计恒等式：资产（含累计折旧抵减）= 负债 + 所有者权益。
P4 折旧政策：P4（年末）的「累计折旧 / 固定资产原值」是否落在年度折旧率区间 3%~10% 之内。
   提醒：P1~P4 是同一会计年度内的 4 个季度，不要按 4 个年度去推算累计折旧。
P5 账外存在性：报表上的资产与收入，是否都能在明细账里找到对应记录。
P6 截止性：收入的确认期间，是否与实际发货/提供劳务的期间一致。
   注意：权责发生制下「本期收款≠本期收入」是正常的，不算异常。

【可报告的手法类型（闭集，只能从中选；若无问题则报 none）】
- offbook：账外账 / 体外循环，存在未入明细账的收入或资产
- cutoff：跨期调节，收入在错误的期间确认
- depreciation：折旧计提不足（累计折旧低于准则要求）
- capitalize：费用资本化，本应费用化的支出被记入资产
- none：未发现异常
""".strip()


# ---------------------------------------------------------------- judge 调用

_JSON_RE = re.compile(r"\{.*\}", re.S)

_TYPE_ALIASES = {
    "offbook": "offbook", "off_book": "offbook", "off-book": "offbook",
    "账外": "offbook", "账外账": "offbook", "体外": "offbook",
    "体外循环": "offbook", "账外账/体外循环": "offbook",
    "cutoff": "cutoff", "cut_off": "cutoff", "cut-off": "cutoff",
    "跨期": "cutoff", "跨期调节": "cutoff", "截止": "cutoff", "截止性": "cutoff",
    "depreciation": "depreciation", "depreciate": "depreciation",
    "折旧": "depreciation", "折旧计提不足": "depreciation",
    "capitalize": "capitalize", "capitalisation": "capitalize",
    "capitalization": "capitalize", "资本化": "capitalize",
    "费用资本化": "capitalize",
    "none": "none", "无": "none", "无异常": "none", "未发现": "none",
}


@dataclass
class Verdict:
    parsed: bool
    flagged: bool | None          # 是否认为存在异常
    kind: str | None              # 归一后的手法类型
    accounts: list[str] = field(default_factory=list)
    period: int | None = None
    reason: str = ""
    raw: str = ""


def parse_verdict(text: str) -> Verdict:
    """从自由文本里抽出结构化判定。

    解析失败必须显式返回 parsed=False —— 它会被算进"基础设施故障"，
    绝不能混进 FNR 的分子或分母（见模块 docstring 纪律 1）。
    """
    if not text or not text.strip():
        return Verdict(False, None, None, raw=text or "")
    m = None
    for cand in _JSON_RE.finditer(text):
        try:
            obj = json.loads(cand.group(0))
            if isinstance(obj, dict) and (
                    "anomaly_found" in obj or "anomaly_type" in obj
                    or "anomaly" in obj):
                m = obj
                break
        except json.JSONDecodeError:
            continue
    if m is None:
        return Verdict(False, None, None, raw=text)

    flag = m.get("anomaly_found", m.get("anomaly", m.get("found")))
    if isinstance(flag, str):
        flag = flag.strip().lower() in ("true", "yes", "1", "是", "存在", "有问题")
    kind_raw = m.get("anomaly_type", m.get("type", m.get("kind")))
    kind = None
    if isinstance(kind_raw, str):
        k = kind_raw.strip().lower()
        for key, val in _TYPE_ALIASES.items():
            if key in k:
                kind = val
                break
        if kind is None:
            low = kind_raw.strip()
            for key, val in _TYPE_ALIASES.items():
                if key in low:
                    kind = val
                    break
    if flag is None and kind is not None:
        flag = kind != "none"
    if flag is True and kind is None:
        kind = "other"          # 说有问题但给不出类型 → 归因层必错
    if flag is False:
        kind = "none"
    acc = m.get("affected_accounts") or m.get("accounts") or []
    if isinstance(acc, str):
        acc = [acc]
    per = m.get("affected_period", m.get("period"))
    try:
        per = int(per) if per is not None else None
    except (TypeError, ValueError):
        per = None
    return Verdict(True, bool(flag), kind,
                   [str(x) for x in acc], per,
                   str(m.get("reason", ""))[:400], text)


def build_prompt(led, arm: str) -> list[dict]:
    """三个 arm 的差别 = 我们帮它多少。"""
    head = {
        "A": "你是一名独立审计复核人员。下面给你一家公司的完整账套（4 个会计期间）。"
             "请判断账套中是否存在异常。",
        "B": "你是一名独立审计复核人员。下面给你一家公司的审计工作底稿"
             "（借贷发生额已加总）。请判断账套中是否存在异常。",
        "C": "你是一名独立审计复核人员。下面给你一家公司的审计工作底稿"
             "（借贷发生额已加总）与本次复核必须执行的程序清单。请逐项执行后判断。",
    }[arm]

    # A 组没有结转口径说明，补一句；B/C 用完整的 _SIGNS。
    # ⚠️ 三组必须共用同一份口径说明：曾经 B 组单独追加了另一句简略说明，
    # 结果把 _SIGNS 里的「P1~P4 属同一会计年度、折旧率 3%~10%」覆盖掉了，
    # 于是 B 组按 4 个年度推算累计折旧 -> 在干净账套上误报。
    # **口径说明只能有一份，且三组必须一致**，否则测的是题面差异不是 judge 能力。
    body = _SIGNS
    blocks = [head, body, render_raw(led) if arm == "A" else render_workpaper(led)]
    if arm == "C":
        blocks.append(CHECKLIST)

    ask = ("\n\n只输出一个 JSON 对象，不要输出任何其它文字。字段：\n"
           '{"anomaly_found": true或false, "anomaly_type": "手法类型", '
           '"affected_accounts": ["科目代码"], "affected_period": 期间整数或null, '
           '"reason": "不超过80字"}')
    if arm != "C":
        ask += ("\n若你认为存在问题，anomaly_type 请用下列之一："
                "offbook（账外账/体外循环）、cutoff（跨期调节）、"
                "depreciation（折旧计提不足）、capitalize（费用资本化）、"
                "none（无异常）。")
    blocks.append(ask)
    return [{"role": "user", "content": "\n\n".join(blocks)}]


# ---------------------------------------------------------------- 实测

ARMS = ("A", "B", "C")
ARM_DESC = {
    "A": "naive（原始凭证+报表，开放式提问，无提示）",
    "B": "workpaper（预求和，消掉算术负担，仍不给差异）",
    "C": "checklist（workpaper + 显式程序清单 + 类型闭集）—— 最宽松",
}


@dataclass
class Cell:
    arm: str
    cond: str# 手法名 或 "clean"
    seed: int
    rep: int = 0                 # 第几次重复调用（用于多数票）
    parsed: bool = True
    flagged: bool | None = None  # 是否认为存在异常
    kind: str | None = None      # 归一后的手法类型
    empty: bool = False
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    attempts: int = 1
    reason: str = ""      # 模型自己给的理由（用于检测"理由与结论矛盾"）


def majority(cells: list[Cell]) -> tuple[Cell, int]:
    """把同一 (arm,cond,seed) 的多次调用**合并成一条**，返回 (合并结果, 分歧标记)。

    ⚠️ 为什么要多数票：实测 deepseek-flash 在 temperature=0 下并不确定，
    同一干净账套连发 4 次里出现过 3 次"无异常" + 1 次"存在跨期调节"。
    单次调用等于用一次抛硬币去决定 go/no-go —— 而 FNR 阈值只有 0.20，
    这种抖动足以伪造出方向性结论。多数票把方差压下来，
    并把"几次重复里仍不一致"显式记成分歧，交由调用方报告。

    合并口径（与 score() 的分层保持一致）：
      - 多数票只看**可解析**的调用（空答案是基础设施故障，不参与投票）
      - flagged 取多数；平票时**取"未报警"**（保守：宁可少判异常，
        也不把抖动算成误报）
      - kind 取多数 flagged=True 里出现最多的类型
      - 分歧 = 该(arm,cond,seed) 内可解析调用对 (flagged,kind) 的不同取值数 > 1
    """
    usable = [c for c in cells if c.parsed and c.flagged is not None]
    base = min(cells, key=lambda c: c.rep)
    if not usable:
        return (Cell(arm=base.arm, cond=base.cond, seed=base.seed,
                     parsed=False, flagged=None, kind=None,
                     empty=all(c.empty for c in cells),
                     tokens_in=sum(c.tokens_in for c in cells),
                     tokens_out=sum(c.tokens_out for c in cells),
                     cost=sum(c.cost for c in cells),
                     latency_ms=int(statistics.median(
                         [c.latency_ms for c in cells if c.latency_ms]) or 0)), 0)

    votes = Counter((c.flagged, c.kind) for c in usable)
    (flag, kind), _ = votes.most_common(1)[0]
    top = votes.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        # 平票：保守取"未报警"，避免把随机抖动记成误报
        for (f, _k), _n in top:
            if f is False:
                flag, kind = False, "none"
                break
    disagree = len(votes) > 1
    merged = Cell(
        arm=base.arm, cond=base.cond, seed=base.seed,
        parsed=True, flagged=flag, kind=kind, empty=False,
        latency_ms=int(statistics.median(
            [c.latency_ms for c in usable if c.latency_ms]) or 0),
        tokens_in=sum(c.tokens_in for c in usable),
        tokens_out=sum(c.tokens_out for c in usable),
        cost=sum(c.cost for c in usable),
        attempts=max(c.attempts for c in usable),
        # 理由取「与最终判定一致」的那一票的代表性理由（取最常见的一条）。
        # ⚠️ 这里必须直接用 Counter，不能回调 majority()——那会无限递归。
        reason=_pick_reason(usable, flag, kind),
    )
    return merged, (1 if disagree else 0)


def _pick_reason(usable: list[Cell], flag, kind) -> str:
    """在投了 (flag, kind) 这票的调用里，取最常见的一条理由。"""
    same = [c.reason for c in usable
            if (c.flagged, c.kind) == (flag, kind) and c.reason]
    if not same:
        return ""
    top, n = Counter(same).most_common(1)[0]
    return top if n > 1 else same[0]


# 模型说"正常/无异常/一致"这类**否定性**措辞
_NEG_REASON = ("无异常", "未见异常", "未发现异常", "正常", "无账外", "折旧计提正常",
               "不构成", "无跨期", "一致", "符合")


def reason_contradiction(cells: list[Cell]) -> dict:
    """统计「结论与理由自相矛盾」的比例。

    实测（arm B，干净账套）：83% 的误报里，模型给出的 `reason` 明写着
    "累计折旧/原值=5%，在3%~10%区间内，折旧正常，**无异常**"，
    而它自己的 `anomaly_found` 字段却是 `true`。
    也就是说它**推理对了、结论写错了**。

    这类错误比单纯算错更值得注意：
      - 它不会出现在任何"准确率"统计里（输出格式合法、类型合法）；
      - RL 里reward 直接取这个 flag，于是**正确的推理被系统性丢弃**；
      - 也无法靠"让模型再仔细点"修好，因为问题出在结论字段而非推理。
    这正是"判分器必须被独立审计"最硬的证据。
    """
    out = {}
    for arm in ARMS:
        sub = [c for c in cells if c.arm == arm and c.parsed
               and c.flagged is True and c.reason]
        if not sub:
            out[arm] = {"n_flagged": 0, "contradiction": 0, "rate": 0.0}
            continue
        contra = [c for c in sub
                  if any(k in c.reason for k in _NEG_REASON)]
        out[arm] = {"n_flagged": len(sub),
                    "contradiction": len(contra),
                    "rate": round(len(contra) / len(sub), 4)}
    return out


def collapse(cells: list[Cell]) -> tuple[list[Cell], int]:
    """整批去重 + 多数票。返回 (每(arm,cond,seed)一条, 分歧条数)。

    第一版没有这一步：run_arm 每次都把**整个** JSONL 读回来，
    而主程序又把它追加进all_cells，于是第2、3 个 arm 的样本被重复计入
    （表里出现1000/600/200 这种不可能的样本数）。
    比例值虽然不变，但 n 被灌了水，Wilson 区间会**假性变窄**——
    而 CI 正是用来判断"是否与0.20 阈值分离"的依据。必须去重。
    """
    groups: dict[tuple[str, str, int], list[Cell]] = defaultdict(list)
    for c in cells:
        groups[(c.arm, c.cond, c.seed)].append(c)
    merged, n_dis = [], 0
    per_arm_dis: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for key in sorted(groups):
        m, d = majority(groups[key])
        merged.append(m)
        n_dis += d
        per_arm_dis[m.arm][0] += d
        per_arm_dis[m.arm][1] += 1
    for arm, (d, n) in per_arm_dis.items():
        COLLECTED_DISAGREE[arm] = (d, n)
    return merged, n_dis


# collapse() 记录的分歧计数，供 score() 读取（避免两处各算一遍算出不同结果）
COLLECTED_DISAGREE: dict[str, tuple[int, int]] = {}


def run_arm(arm: str, conditions: list[str], n_seeds: int,
            client_factory: Callable[[], object],
            price_of: Callable[[str, int, int], float],
            out_path: Path, workers: int = 8,
            max_tokens: int = 8192, repeat: int = 1) -> list[Cell]:
    """跑完一个 arm 的全部 (条件, seed)，结果增量落 JSONL。

    幂等：已存在的 (arm,cond,seed,rep) 直接复用，中断后重跑不会重复付费。

    ⚠️ `repeat` 不是"更准一点"的可选项，而是**结论能否成立的前提**。
    实测：deepseek-flash 在 `temperature=0` 下**同一个干净账套连发4 次，
    前 3 次答"无异常"、第 4 次答"存在跨期调节(cutoff)"**——HTTP 200、格式正确、
    理由也写得像模像样。也就是说这个网关并不真的确定性，
    单次调用的结果里有随机成分。
    而FNR 是**比例**，比例的抽样误差会直接决定 go/no-go 判据
    （阈值 0.20，n=160 时 95%CI 半宽约 0.075）——单次调用量出来的差异
    有可能纯粹是这份抖动。所以 repeat>=2 时按**多数票**汇总一条Cell，
    并把分歧数报出来：分歧率高说明该模型在该题上不稳定，
    那是真实结论，不是噪声。
    """
    done: dict[tuple[str, str, int, int], Cell] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            c = Cell(**d)
            done[(c.arm, c.cond, c.seed, c.rep)] = c

    jobs = [(arm, cond, s, rep) for cond in conditions for s in range(n_seeds)
            for rep in range(repeat) if (arm, cond, s, rep) not in done]
    if not jobs:
        return list(done.values())

    lock = threading.Lock()
    fh = out_path.open("a", encoding="utf-8")
    local = threading.local()
    counters = defaultdict(int)

    def client() -> object:
        if not hasattr(local, "c"):
            local.c = client_factory()
        return local.c

    def one(job) -> None:
        a, cond, seed, rep = job
        led = make_seed_ledger(seed)
        if cond != "clean":
            injected = led.clone()
            FRAUD_OPS[cond].apply(injected, {})
            dic = certify(led, cond, {}, f"{a}-{cond}-{seed}")
            if not dic.valid:
                # DIC 无效 = 真值不可信，这条样本必须弃掉而不是硬算
                with lock:
                    counters["dic_invalid"] += 1
                return
            led = injected

        cl = client()
        attempts = 0
        for attempt in range(2):
            attempts += 1
            try:
                resp = cl.chat_detailed(build_prompt(led, a),
                                        max_tokens=max_tokens)
            except Exception as exc:                    # 网络/网关错误
                with lock:
                    counters[f"error:{type(exc).__name__}"] += 1
                time.sleep(2 * (attempt + 1))
                continue
            v = parse_verdict(resp.text)
            if (resp.empty_text or resp.truncated) and attempt == 0:
                # 空答案几乎都是 thinking 烧光预算，提高上限重试一次。
                continue
            cell = Cell(
                arm=a, cond=cond, seed=seed, rep=rep, parsed=v.parsed,
                flagged=v.flagged, kind=v.kind,
                empty=resp.empty_text or resp.truncated,
                latency_ms=resp.latency_ms, reason=v.reason,
                tokens_in=resp.usage.tokens_in,
                tokens_out=resp.usage.tokens_out,
                cost=price_of(resp.model, resp.usage.tokens_in,
                              resp.usage.tokens_out),
                attempts=attempts,
            )
            with lock:
                fh.write(json.dumps(cell.__dict__, ensure_ascii=False) + "\n")
                fh.flush()
                counters["done"] += 1
            return
        cell = Cell(arm=a, cond=cond, seed=seed, rep=rep, parsed=False,
                    flagged=None, kind=None, empty=True, latency_ms=0,
                    attempts=attempts)
        with lock:
            fh.write(json.dumps(cell.__dict__, ensure_ascii=False) + "\n")
            fh.flush()
            counters["unresolved"] += 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    fh.close()
    cells = [Cell(**json.loads(line))
             for line in out_path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if counters:
        print(f"  [arm {arm}] {dict(counters)}")
    return cells


def score(cells: list[Cell]) -> dict:
    """两层 FNR + FPR，严格口径。

    ⚠️ 入参应当是 `collapse()` 之后的**去重**列表。传原始列表会重复计数，
    把 n 灌水、让 Wilson 区间假性变窄（第一版就犯过，表现为
    "1000/600/200"这种不可能的样本数）。

    分母纪律：
      检测层 FNR 分母 = **可解析**的注入样本数（空答案/解析失败剔除）
      归因层 FNR 分母 = 检测层已检出的样本数
      端到端   FNR 分母 = 可解析的注入样本数
      FPR           分母 = 可解析的干净样本数
    空/解析失败率单列，不进任何 FNR 分母。
    """
    out: dict[str, dict] = {}
    for arm in ARMS:
        sub = [c for c in cells if c.arm == arm]
        if not sub:
            continue
        usable = [c for c in sub if c.parsed and c.flagged is not None]
        empty = sum(1 for c in sub if c.empty)
        unparsed = sum(1 for c in sub if not c.parsed)
        # 分歧率只能在**未折叠**的列表上算；score() 收到的是折叠后的，
        # 所以由调用方经collapse() 传入。这里只保留占位，真实值由 runner 填。
        n_total = len(sub)

        inj = [c for c in usable if c.cond != "clean"]
        cln = [c for c in usable if c.cond == "clean"]

        det_miss = sum(1 for c in inj if not c.flagged)
        detected = [c for c in inj if c.flagged]
        attr_err = sum(1 for c in detected if c.kind != c.cond)
        e2e_err = sum(1 for c in inj if not (c.flagged and c.kind == c.cond))
        fp = sum(1 for c in cln if c.flagged)

        per_op = {}
        for op in sorted(FRAUD_OPS):
            o = [c for c in inj if c.cond == op]
            if o:
                m = sum(1 for c in o if not (c.flagged and c.kind == op))
                per_op[op] = {
                    "n": len(o),
                    "e2e_fnr": round(m / len(o), 4),
                    "det_fnr": round(sum(1 for c in o if not c.flagged) / len(o), 4),
                    "ci95": wilson(m, len(o)),
                }

        # 归一后的手法分布 —— 用来排除"judge 只会报一种"的退化解。
        kind_dist: dict[str, int] = defaultdict(int)
        for c in detected:
            kind_dist[c.kind or "null"] += 1

        out[arm] = {
            "desc": ARM_DESC[arm],
            "n_usable": len(usable),
            "n_injected": len(inj),
            "n_clean": len(cln),
            "n_empty": empty,
            "n_unparsed": unparsed,
            "empty_rate": round(empty / len(sub), 4) if sub else 0.0,
            "unparsed_rate": round(unparsed / len(sub), 4) if sub else 0.0,
            "det_fnr": round(det_miss / len(inj), 4) if inj else 0.0,
            "det_fnr_ci95": wilson(det_miss, len(inj)),
            "attr_fnr": round(attr_err / len(detected), 4) if detected else 0.0,
            "e2e_fnr": round(e2e_err / len(inj), 4) if inj else 0.0,
            "e2e_fnr_ci95": wilson(e2e_err, len(inj)),
            "fpr": round(fp / len(cln), 4) if cln else 0.0,
            "fpr_ci95": wilson(fp, len(cln)),
            "per_op": per_op,
            "kind_dist": dict(kind_dist),
            "median_latency_ms": int(statistics.median(
                [c.latency_ms for c in sub if c.latency_ms])) if sub else 0,
            "n_collapsed": n_total,
            "disagree_rate": (round(COLLECTED_DISAGREE[arm][0]
                                    / COLLECTED_DISAGREE[arm][1], 4)
                              if COLLECTED_DISAGREE.get(arm, (0, 0))[1] else 0.0),
        }
    return out


def verdict(res: dict, threshold: float = 0.20,
            min_usable_per_arm: int = 30) -> dict:
    """按**跑之前写死的**规则给结论。

    ⚠️ 这里有一道必须存在的守卫：**数据不够就不给结论**（返回 INCOMPLETE）。

    第一版没有这道守卫，后果是实测踩到的：试点 5 个样本里 4 个是空答案
    （thinking 烧光 token），score() 把空样本剔除出分母后分母只剩 1，
    于是报出"FNR = 0.000 → NO-GO（转向）"。这是**假结论**——
    不是 judge 看得准，而是它几乎没作答；而"转向"是个代价极大的动作。

    更隐蔽的是它**恰好落在最危险的方向**：样本越少，FNR 越容易是 0
    （n=1 时全对就是 0.000）。也就是**数据故障会伪造出"该转向"的信号**。
    所以宁可不给结论，也不给一个样本不足的结论。

    守卫条件（任一不满足即 INCOMPLETE，不给方向性建议）：
      - 最宽松 arm C 缺失
      - C 的可用注入样本 < min_usable_per_arm
      - C 的空答案率 > 20%（基础设施故障主导，测的是故障不是能力）
    """
    if "C" not in res:
        return {"decision": "INCOMPLETE（不给结论）",
                "why": "最宽松 arm (C) 未完成"}

    c = res["C"]
    n_inj = sum(d["n"] for d in c.get("per_op", {}).values())
    reasons = []
    if n_inj < min_usable_per_arm:
        reasons.append(f"可用注入样本仅 {n_inj} < {min_usable_per_arm}"
                       f"（样本不足时 FNR 极易假性偏低）")
    if c.get("empty_rate", 0) > 0.20:
        reasons.append(f"空答案率 {c['empty_rate']:.1%} > 20%"
                       f"（基础设施故障主导，测的不是 judge 能力）")
    if reasons:
        return {"decision": "INCOMPLETE（不给结论）",
                "why": "；".join(reasons),
                "n_usable_injected": n_inj,
                "empty_rate": c.get("empty_rate"),
                "hint": "先修基础设施（关 thinking、加大 max_tokens）再重跑，"
                        "不要拿这个结果去汇报或转向。"}

    fnr = c["e2e_fnr"]
    lo, hi = c["e2e_fnr_ci95"]
    hold = fnr >= threshold
    return {
        "decision": "GO（叙事成立，继续）" if hold else "NO-GO（转向）",
        "threshold": threshold,
        "rule": "FNR*(最宽松 arm C 的端到端漏判率) >= 0.20 则继续，否则转向",
        "FNR_star": fnr,
        "FNR_star_ci95": [lo, hi],
        "n_usable_injected": n_inj,
        "ci_excludes_threshold": (lo >= threshold) or (hi < threshold),
        "supporting": {
            "A_e2e_fnr": res.get("A", {}).get("e2e_fnr"),
            "B_e2e_fnr": res.get("B", {}).get("e2e_fnr"),
            "C_fpr": c.get("fpr"),
            "C_det_fnr": c.get("det_fnr"),
            "C_attr_fnr": c.get("attr_fnr"),
            "C_empty_rate": c.get("empty_rate"),
        },
    }
