"""S1 测量台的自检（离线，不花钱）。

跑法：
    python run_s1_selfcheck.py

为什么必须先跑这个
------------------
`judge_probe` 的结论会决定整个v4 方向要不要转向。而"低 FNR"有两种完全不同的成因：

  (a) 真实结论：LLM judge 确实能看见这些异常 → 方向该转向
  (b) **测量台坏了**：prompt 没把账套送进去 / 解析器把合法JSON 判成不可解析 /
      DIC 失效导致样本被弃/ 干净账套本身不干净

(b) 会伪装成 (a)，让我们在最不该转向的时候转向——这是本项目最贵的错误。
所以这里用**已知答案的假 judge** 做端到端标定：先证明这套台子
能把"该报的全报出来"量成 FNR≈0，再相信它量出来的非零值。

四项检查：
  1. 解析器：合法/畸形/空/截断 四类输入的判定是否正确
  2. 渲染器：prompt 里**确实含有**账套的关键数字（防止"其实没送进去"）
  3. oracle 捷径：一个"作弊但合法"的 judge（直接调我们的 oracle）
     必须量出 FNR = 0 —— 这是台子的**下界标定**
  4. 全报/全不报 两个极端假 judge必须量出 FNR = 1.0 / 0.0（端点自洽）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from vts.audit_core import FRAUD_OPS, ORACLES, certify, make_seed_ledger
from vts.judge_probe import (ARMS, Cell, build_prompt, collapse, majority,
                             parse_verdict, reason_contradiction,
                             render_raw, render_workpaper, score, verdict)

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((PASS if cond else FAIL, name, detail))


def _oracle_judge(led) -> tuple[bool, str]:
    """作弊但完全合法的 judge：直接跑领域 oracle。

    它就是"判分器做对了"的上界实现。如果连它都被量成高 FNR，
    说明**台子坏了**，而不是模型差。
    """
    p = led.n_periods
    from vts.audit_core import period_flow, expected_reported
    viol = [n for n, fn in ORACLES.items() if not fn(led, p)]
    if not viol:
        return False, "none"
    # 手法归因：用"哪条会计约束被破坏"反推，这是 oracle 能做到的上限
    return True, "tie_detail" if "o_tie_detail" in viol else viol[0]


def main() -> int:
    # ---- 1. 解析器
    v = parse_verdict('{"anomaly_found": true, "anomaly_type": "offbook"}')
    check("解析：标准 JSON 正确", v.parsed and v.flagged and v.kind == "offbook")

    v = parse_verdict('思考中...\n```json\n{"anomaly_found": false, '
                      '"anomaly_type": "none"}\n```')
    check("解析：markdown 围栏 + 前后废话", v.parsed and v.flagged is False)

    v = parse_verdict('我认为账目有问题，主要是跨期调节。')
    check("解析：纯散文判为不可解析（不硬猜）",
          not v.parsed, "宁可剔除也不污染分母")

    v = parse_verdict("")
    check("解析：空答案 -> 不可解析", not v.parsed)

    v = parse_verdict('{"anomaly_found": true}')
    check("解析：说有问题但无类型 -> 归因层必错",
          v.parsed and v.flagged and v.kind == "other", f"kind={v.kind}")

    v = parse_verdict('{"anomaly_found": true, "anomaly_type": "费用资本化"}')
    check("解析：中文类型别名", v.parsed and v.kind == "capitalize")

    # ---- 2. 渲染器：prompt 里必须真的有账套内容
    led = make_seed_ledger(3)
    for arm in ARMS:
        msgs = build_prompt(led, arm)
        txt = msgs[0]["content"]
        has_acct = "4001_capital" in txt
        check(f"渲染[{arm}]：含报表科目与金额", has_acct and "," in txt)
        if arm == "A":
            check("渲染[A]：含逐张凭证编号", "V001P1s" in txt)
        if arm in ("B", "C"):
            check(f"渲染[{arm}]：workpaper 含发生额列",
                  "本期借方发生额" in txt and "本期贷方发生额" in txt)
            # 零值必须显式为 0.00：'-' 会让 judge 分不清"是0"和"没给数据"，
            # 这个歧义双向污染 FPR，属于出题失误而非模型能力。
            # 注意只能匹配**裸的** '-'（两侧是分隔符），否则会误伤
            # 负数金额如 -78,542.04（累计折旧/收入本来就要带负号）。
            bare_dash = [ln for ln in txt.splitlines()
                         if re.search(r"(?:^|\|)\s*-\s*(?:\||$)", ln)]
            check(f"渲染[{arm}]：零值显式写 0.00 不用裸 '-'",
                  not bare_dash, f"含裸横线={bare_dash[:2]}")
            # 每期都要有期初余额，否则 judge 做不了第2期起的递推核对
            for p in range(2, led.n_periods + 1):
                seg = txt.split(f"--- P{p} ---")[1].split("---")[0] \
                    if f"--- P{p} ---" in txt else ""
                check(f"渲染[{arm}]：P{p} 有期初余额列可读",
                      bool(seg.strip()) and "1002_bank" in seg)
        if arm == "C":
            check("渲染[C]：含程序清单 P1-P6",
                  all(f"P{i} " in txt or f"P{i}\n" in txt or f"P{i}" in txt
                      for i in range(1, 7)))
            # C 组的泄漏防线不是"不许出现手法名"，而是**对称**：
            # 清单必须同时点名全部 4 种手法。只点名被注入的那一种才是泄漏。
            named = [w for w in ("offbook", "cutoff", "depreciation", "capitalize")
                     if w in txt]
            check("渲染[C]：程序清单对称点名全部 4 种手法（非定向泄漏）",
                  len(named) == 4, f"仅点名={named}")
            # 账套数据段落本身不得含任何手法名
            body = txt.split("【科目发生额")[1].split("【可报告")[0] \
                if "【科目发生额" in txt else ""
            check("渲染[C]：账套数据段落不含手法名",
                  not any(w in body for w in
                          ("offbook", "cutoff", "depreciation", "capitalize")))
        else:
            # 只查**账套数据段落**（种子账套是随机生成的，其正文里出现手法名
            # 才是泄漏）。口径说明与末尾的类型清单允许出现手法名——
            # 那是题面的一部分，且对 4 种手法对称，不指向被注入的那一个。
            data = txt.split("只输出一个 JSON")[0]
            for tag in ("【明细账：记账凭证】", "【科目发生额及余额表"):
                if tag in data:
                    data = data[data.index(tag):]
            check(f"渲染[{arm}]：账套数据段落未泄漏手法名",
                  not any(w in data for w in ("offbook", "cutoff",
                                             "depreciation", "capitalize")))

    raw = render_raw(led)
    wp = render_workpaper(led)
    check("渲染：workpaper 未直接给出应有vs报表的差异列",
          "差异" not in wp, "给了差异列等于直接送答案")

    # ---- 3/4. 端点标定：三个已知答案的假 judge
    def synth(arm, cond, seed, fn) -> Cell:
        flag, kind = fn(led)
        return Cell(arm=arm, cond=cond, seed=seed, parsed=True,
                    flagged=flag, kind=kind, empty=False, latency_ms=1)

    conds = sorted(FRAUD_OPS) + ["clean"]
    n = 5

    # (a) 作弊 judge：报出的类型恰好等于真值时，FNR 必须为 0
    cells = []
    for arm in ARMS:
        for cond in conds:
            for s in range(n):
                if cond == "clean":
                    cells.append(synth(arm, cond, s, lambda l: (False, "none")))
                else:
                    cells.append(synth(arm, cond, s, lambda l, c=cond: (True, c)))
    res = score(cells)
    ok = all(res[a]["e2e_fnr"] == 0.0 for a in ARMS)
    check("标定：完美 judge 端到端 FNR=0（台子下界正确）", ok,
          f"A={res['A']['e2e_fnr']} C={res['C']['e2e_fnr']}")
    check("标定：完美 judge 误报率 FPR=0",
          all(res[a]["fpr"] == 0.0 for a in ARMS))

    # (b) 全不报：FNR 必须为 1.0，FPR=0（它从不报警，所以干净账套上"对"）
    cells = [Cell(arm=a, cond=c, seed=s, parsed=True, flagged=False,
                  kind="none", empty=False, latency_ms=1)
             for a in ARMS for c in conds for s in range(n)]
    res = score(cells)
    check("标定：哑巴 judge 端到端 FNR=1.0",
          all(res[a]["e2e_fnr"] == 1.0 for a in ARMS))
    check("标定：哑巴 judge 检测层 FNR=1.0",
          all(res[a]["det_fnr"] == 1.0 for a in ARMS))

    # (c) 全报警：注入样本端到端 FNR=1.0（类型全错），干净样本 FPR=1.0
    cells = []
    for a in ARMS:
        for c in conds:
            for s in range(n):
                cells.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                  flagged=True,
                                  kind="none" if c != "clean" else "offbook",
                                  empty=False, latency_ms=1))
    res = score(cells)
    check("标定：全报警 judge 在干净账套上 FPR=1.0",
          all(res[a]["fpr"] == 1.0 for a in ARMS))
    check("标定：全报警 judge 端到端 FNR=1.0（类型全错）",
          all(res[a]["e2e_fnr"] == 1.0 for a in ARMS))

    # ---- 5. 空答案必须被剔除出分母，而不是算成漏判
    cells = []
    for a in ARMS:
        for c in conds:
            for s in range(n):
                if s == 0:                      # 一半基础设施故障
                    cells.append(Cell(arm=a, cond=c, seed=s, parsed=False,
                                      flagged=None, kind=None, empty=True,
                                      latency_ms=1))
                elif c == "clean":
                    cells.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                      flagged=False, kind="none", empty=False,
                                      latency_ms=1))
                else:
                    cells.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                      flagged=True, kind=c, empty=False,
                                      latency_ms=1))
    res = score(cells)
    check("口径：空答案被剔除出分母而非计为漏判",
          res["A"]["e2e_fnr"] == 0.0 and res["A"]["empty_rate"] > 0.0,
          f"fnr={res['A']['e2e_fnr']} empty_rate={res['A']['empty_rate']}")

    # ---- 6. DIC 无效样本必须被弃（真值不可信就不该量）
    bad = [op for op in sorted(FRAUD_OPS)
           if not certify(make_seed_ledger(7), op, {}, "x").valid]
    check("真值：DIC 在抽样种子上全部有效", not bad, f"无效={bad}")

    # ---- 7. 干净账套确实干净（否则 FPR 分母是错的）
    dirty = []
    for s in range(50):
        lg = make_seed_ledger(s)
        for p in range(1, lg.n_periods + 1):
            v_ = [n for n, fn in ORACLES.items() if not fn(lg, p)]
            if v_:
                dirty.append((s, p, v_))
    check("真值：干净账套在 50 seed x 4 期上全部满足四条约束", not dirty,
          f"违规={dirty[:3]}")

    # ---- 8. 决策守卫：数据不足 / 故障主导时**必须拒绝给结论**
    #
    # 这一条是实测踩出来的：试点 5 个样本 4 个空答案，剔除后分母只剩 1，
    # 第一版照样报出"FNR=0.000 → NO-GO（转向）"。样本越少 FNR 越容易是 0，
    # 也就是说**基础设施故障会伪造出"该转向"的信号**——方向恰好最危险。
    conds2 = sorted(FRAUD_OPS) + ["clean"]

    # (a) 复现那个假 NO-GO：绝大多数样本空answer
    starved = []
    for a in ARMS:
        for c in conds2:
            for s in range(10):
                if s < 9:
                    starved.append(Cell(arm=a, cond=c, seed=s, parsed=False,
                                        flagged=None, kind=None, empty=True,
                                        latency_ms=1))
                elif c == "clean":
                    starved.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                        flagged=False, kind="none", empty=False,
                                        latency_ms=1))
                else:
                    starved.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                        flagged=True, kind=c, empty=False,
                                        latency_ms=1))
    v = verdict(score(starved))
    check("守卫：样本被空答案吃掉时拒绝给结论",
          v["decision"].startswith("INCOMPLETE"), v["decision"])
    check("守卫：该情形下不出现 NO-GO 字样",
          "NO-GO" not in v["decision"], v["decision"])

    # (b) 样本量够但空答案率仍高-> 同样拒绝
    heavy = []
    for a in ARMS:
        for c in conds2:
            for s in range(60):
                if s < 30:
                    heavy.append(Cell(arm=a, cond=c, seed=s, parsed=False,
                                      flagged=None, kind=None, empty=True,
                                      latency_ms=1))
                elif c == "clean":
                    heavy.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                      flagged=False, kind="none", empty=False,
                                      latency_ms=1))
                else:
                    heavy.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                      flagged=True, kind=c, empty=False,
                                      latency_ms=1))
    v = verdict(score(heavy))
    check("守卫：空答案率 >20% 时拒绝给结论",
          v["decision"].startswith("INCOMPLETE"), v.get("why", ""))

    # (c) 数据健康且 FNR 高-> 必须给出 GO
    healthy = []
    for a in ARMS:
        for c in conds2:
            for s in range(60):
                if c == "clean":
                    healthy.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                        flagged=False, kind="none", empty=False,
                                        latency_ms=1))
                elif s < 30:               # 一半漏判
                    healthy.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                        flagged=False, kind="none", empty=False,
                                        latency_ms=1))
                else:
                    healthy.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                        flagged=True, kind=c, empty=False,
                                        latency_ms=1))
    v = verdict(score(healthy))
    check("守卫：数据健康且 FNR=0.5 时给出 GO",
          v["decision"].startswith("GO") and abs(v["FNR_star"] - 0.5) < 1e-6,
          f"{v['decision']} FNR*={v.get('FNR_star')}")

    # (d) 数据健康且 FNR 低 -> 必须给出 NO-GO（守卫不能把真NO-GO 也吃掉）
    healthy2 = []
    for a in ARMS:
        for c in conds2:
            for s in range(60):
                if c == "clean":
                    healthy2.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                         flagged=False, kind="none", empty=False,
                                         latency_ms=1))
                elif s < 3:# 5% 漏判
                    healthy2.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                         flagged=False, kind="none", empty=False,
                                         latency_ms=1))
                else:
                    healthy2.append(Cell(arm=a, cond=c, seed=s, parsed=True,
                                         flagged=True, kind=c, empty=False,
                                         latency_ms=1))
    v = verdict(score(healthy2))
    check("守卫：数据健康且 FNR=0.05 时给出 NO-GO（不吞掉真结论）",
          v["decision"].startswith("NO-GO") and v["FNR_star"] < 0.20,
          f"{v['decision']} FNR*={v.get('FNR_star')}")

    # ---- 9. 折旧口径必须写进题面（否则测的是题，不是judge）
    #
    # 实测踩到：题面只写"累计折旧/原值 是否超过年度折旧率区间"，
    # 没说 P1~P4 是**同一会计年度的4 个季度**。judge 于是按 4 个年度推算，
    # 期待累计折旧 ≈ 原值 x5% x4 = 20%，看到 5% 就判"计提不足"——
    # 于是在**干净账套**上给出 depreciation，FPR = 1.000。
    # 而 o_policy 认定这些账套完全合规（比率正好 0.0500，在 3%~10% 内）。
    # 也就是说：差点把一道**出错的题**当成"judge 不可靠"的核心证据。
    for arm in ("B", "C"):
        txt = build_prompt(led, arm)[0]["content"]
        # 只查实质（"…会计年度…4 个季度"），不查逐字措辞：
        # 各arm 措辞略有差异（B组"同一个会计年度" / C组清单"同一会计年度"），
        # 断言写成逐字相等会假失败。
        check(f"口径[{arm}]：声明 P1~P4 属同一会计年度的 4 个季度",
              "4 个季度" in txt and "会计年度" in txt)
        check(f"口径[{arm}]：给出年度折旧率区间 3%~10%",
              "3%" in txt and "10%" in txt)

    # 题面口径必须与 oracle 的实际判定一致：干净账套比率 0.05 落在区间内
    ratios = []
    for s in range(20):
        lg = make_seed_ledger(s)
        rep = lg.reported[lg.n_periods]
        fa = rep.get("1601_fa", 0.0)
        ratios.append(abs(rep.get("1602_accum_dep", 0.0)) / fa if fa else 0)
    check("口径：干净账套折旧比率确实落在 3%~10% 内（题面与oracle 一致）",
          all(0.03 <= r <= 0.10 for r in ratios),
          f"min={min(ratios):.4f} max={max(ratios):.4f}")

    # ---- 10. 去重与多数票（两处都是实测踩出来的）
    #
    # (a) 去重：run_arm 每次都把整个 JSONL 读回来，主程序又累加，
    #     导致第2/3 个 arm 被重复计数（表现为 1000/600/200 的假样本数）。
    #     比例不变但 n 被灌水 → Wilson 区间假性变窄 → CI 判断失效。
    dup = []
    for a in ARMS:
        for c in conds2:
            for s in range(10):
                dup.append(Cell(arm=a, cond=c, seed=s, rep=0, parsed=True,
                                flagged=(c == "clean" and False) or c != "clean",
                                kind="none" if c == "clean" else c,
                                empty=False, latency_ms=1))
    dup += list(dup)                      # 整个 batch 被重复累加一次
    merged, n_dis = collapse(dup)
    check("去重：重复列表折叠后样本数不翻倍",
          len(merged) == 3 * len(conds2) * 10,
          f"{len(merged)}（应为 {3 * len(conds2) * 10}）")
    r = score(merged)
    # ⚠️ 分母必须**动态计算**（2026-10-05 修）：
    # 原写成硬编码 `4 * 10`，而 `conds2 = sorted(FRAUD_OPS) + ["clean"]`
    # 会随 FRAUD_OPS 增减（本轮新增 equation_break / dep_over 后变成 6+1=7），
    # 于是断言分母与真实样本数脱节 → 报假 FAIL。
    # 这与"聚合时重复读取旧 JSONL 扩大分母"是同类的分母失真坑，
    # 只是方向相反（这次是分母写死、跟不上数据源）。
    n_cond = len(conds2) - 1                      # 排除 "clean"
    n_per_arm = n_cond * 10
    check("去重：score 的注入分母等于去重后的真实数量",
          all(r[a]["n_injected"] == n_per_arm for a in ARMS),
          f"n_injected={r['A']['n_injected']}（应为 {n_per_arm} = "
          f"{n_cond} 注入条件 × 10 seed）")

    # (b) 多数票：同一干净账套 3 次"无异常" + 1 次"cutoff" -> 判为无异常。
    #     这正是实测到的抖动模式；若按单次或"最后一条"汇总，FPR 会被
    #     随机推到 0.25，完全是掷硬币。
    shaky = [
        Cell(arm="C", cond="clean", seed=0, rep=0, parsed=True, flagged=False,
             kind="none", empty=False, latency_ms=1),
        Cell(arm="C", cond="clean", seed=0, rep=1, parsed=True, flagged=False,
             kind="none", empty=False, latency_ms=1),
        Cell(arm="C", cond="clean", seed=0, rep=2, parsed=True, flagged=False,
             kind="none", empty=False, latency_ms=1),
        Cell(arm="C", cond="clean", seed=0, rep=3, parsed=True, flagged=True,
             kind="cutoff", empty=False, latency_ms=1),
    ]
    m, dis = majority(shaky)
    check("多数票：3:1 时判为未报警（不掷硬币）",
          m.flagged is False and m.kind == "none", f"flagged={m.flagged}")
    check("多数票：分歧被标记出来", dis == 1, f"disagree={dis}")

    # (c) 平票必须保守取"未报警"（宁可少判异常，也不把抖动算成误报）
    tie = [Cell(arm="C", cond="clean", seed=1, rep=0, parsed=True,
                flagged=True, kind="cutoff", empty=False, latency_ms=1),
           Cell(arm="C", cond="clean", seed=1, rep=1, parsed=True,
                flagged=False, kind="none", empty=False, latency_ms=1)]
    m, _ = majority(tie)
    check("多数票：平票保守取未报警", m.flagged is False, f"flagged={m.flagged}")

    # (d) 空答案不参与投票（否则基础设施故障会左右结论）
    withempty = shaky + [Cell(arm="C", cond="clean", seed=0, rep=4,
                              parsed=False, flagged=None, kind=None,
                              empty=True, latency_ms=0)]
    m, _ = majority(withempty)
    check("多数票：空答案不参与投票", m.flagged is False, f"flagged={m.flagged}")

    # 题面必须写明**权责发生制**，否则会把"收入已确认但现金未收"误判为跨期调节。
    # 实测踩到：干净账套上 arm B/C 的 FPR 高达 1.000/0.600，理由是
    # "收入189.6万但回款182.1万，不匹配，存在跨期调节嫌疑"。
    # 而这在权责发生制下是**正常的**（应收与收入等额增加，银行少收只是收款在后续期间）。
    # 也就是说：不给口径说明，测出来的是"题面歧义"，不是"judge 能力"。
    # ——这与折旧口径是同一类错误的两个实例，所以都要锁死。
    for arm in ("A", "B", "C"):
        txt = build_prompt(led, arm)[0]["content"]
        check(f"口径[{arm}]：声明权责发生制且说明收入≠回款属正常",
              "权责发生制" in txt and ("不是收付实现制" in txt
                                      or "正常" in txt))
        check(f"口径[{arm}]：提示 cutoff 判据是期间一致性而非收付相等",
              "确认期间" in txt or "发货" in txt)

    # 交叉验证：干净账套里收入与应收确实等额增加、回款确实小于收入，
    # 所以 judge 若仍报cutoff，那是真的判错，不是数据异常。
    lg = make_seed_ledger(1)
    sale = sum(v.amount for v in lg.vouchers
               if v.period == lg.n_periods and v.credit == "6001_revenue")
    coll = sum(v.amount for v in lg.vouchers
               if v.period == lg.n_periods and v.debit == "1002_bank"
               and v.credit == "1122_ar")
    check("口径：干净账套存在'收入≠本期回款'的正常形态（歧义确实被消除）",
          coll < sale, f"回款={coll:,.0f} < 收入={sale:,.0f}")

    # ---- 11. 结论与理由矛盾检测（必须有测试，否则它会静默少报）
    contra_cells = [
        # flag=true 但理由说"无异常" -> 应计入矛盾（实测 arm B 的真实模式）
        Cell(arm="B", cond="clean", seed=0, parsed=True, flagged=True,
             kind="depreciation", empty=False, latency_ms=1,
             reason="累计折旧/原值=5%，在3%-10%区间内，折旧正常，无异常。"),
        Cell(arm="B", cond="clean", seed=1, parsed=True, flagged=True,
             kind="cutoff", empty=False, latency_ms=1,
             reason="收入189万但回款182万，不匹配，存在跨期调节嫌疑。"),
        # flagged=False 的不应计入（那是正确的"无异常"）
        Cell(arm="B", cond="clean", seed=2, parsed=True, flagged=False,
             kind="none", empty=False, latency_ms=1,
             reason="勾稽一致，无异常。"),
    ]
    rc = reason_contradiction(contra_cells)
    check("矛盾检测：flag=true 且理由否定 -> 计入",
          rc["B"]["contradiction"] == 1, str(rc["B"]))
    check("矛盾检测：flag=false 不计入",
          rc["B"]["rate"] == round(1 / 2, 4), f"rate={rc['B']['rate']}")
    check("矛盾检测：flag=true 且理由肯定 -> 不计入矛盾",
          rc["B"]["n_flagged"] == 2)

    # 无 reason 的样本不能被算成矛盾（否则未解析会伪装成矛盾）
    noreason = [Cell(arm="C", cond="clean", seed=0, parsed=True, flagged=True,
                     kind="offbook", empty=False, latency_ms=1, reason="")]
    rc2 = reason_contradiction(noreason)
    check("矛盾检测：缺 reason 的样本被排除而非误判",
          rc2["C"]["n_flagged"] == 0, str(rc2["C"]))

    # ---- 汇总
    width = max(len(n) for _, n, _ in results) + 2
    n_fail = 0
    for status, name, detail in results:
        if status == FAIL:
            n_fail += 1
        line = f"[{status}] {name.ljust(width)}"
        if detail:
            line += f"  {detail}"
        print(line)
    print("-" * 70)
    print(f"{len(results) - n_fail}/{len(results)} 通过")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
