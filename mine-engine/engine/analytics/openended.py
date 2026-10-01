"""开放式评测度量：时间轴、成本轴、饱和检测、Performance 归一化。

理论依据：ALE-Bench（Sakana AI × AtCoder，arXiv:2506.09050，NeurIPS'25）。

ALE-Bench 解决的是 ALE 没解决、而对我们同样致命的问题：**分数会饱和**。
它的答案是三条，本模块把这三条变成可调用的函数：

    1. 连续分 + 开放式上限
       题目是真最优解不可达的优化问题，所以分数永远有上升空间。
       → `saturation_check()`：拟合时间-分数曲线，估计渐近线还有多少空间。

    2. 时间预算必须报
       1h 58.8 → 几小时 77.7 → 几天 87.6 → 1 周 92.1。
       → `long_horizon_curve()`：算边际收益，判断"多给时间还值不值"。

    3. 成本必须报，且要做归一化
       ALE-Agent 1879 分 / $100.33；OpenHands 905 分 / $3.25。只报分数是失真。
       → `cost_quality_frontier()`：帕累托前沿 + 性价比。
       → `performance_elo()`：把分数放回人类分布，得到 Elo-like Performance。

设计原则（与 env_quality.py 一致）：
1. 零外部依赖，只用标准库。
2. 度量本身要能被证伪：数据不够就如实报 `None` / `insufficient_data`，
   不允许"算不出就悄悄给个好看的数"。

用法：
    from engine.analytics import saturation_check, cost_quality_frontier

    # 时间轴：给更多时间还能涨多少？
    sat = saturation_check([(3600, 0.588), (14400, 0.777),
                            (259200, 0.876), (604800, 0.921)])
    print(sat["headroom"], sat.verdict)

    # 成本轴：谁在帕累托前沿上？
    fr = cost_quality_frontier([
        {"name": "OpenHands",  "cost": 3.25,   "score": 905},
        {"name": "Self-Refine","cost": 11.10,  "score": 1198},
        {"name": "ALE-Agent",  "cost": 100.33, "score": 1879},
    ])
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "rank_percentile",
    "performance_elo",
    "long_horizon_curve",
    "saturation_check",
    "cost_quality_frontier",
    "budget_report",
]


# --------------------------------------------------------------------------
# 0. 工具
# --------------------------------------------------------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 4)


# --------------------------------------------------------------------------
# 1. Performance 归一化：把分数放回人类分布
# --------------------------------------------------------------------------

def rank_percentile(
    score: float,
    human_scores: Sequence[float],
    higher_is_better: bool = True,
) -> Dict[str, Any]:
    """算 `score` 放在人类成绩分布里排第几。

    ALE-Bench 不报原始分，而报 Performance（相当于人类第几名），
    因为合成题的绝对分没有外部意义。

    返回：
        rank        名次（1 最好）
        n           人类样本量
        top_pct     "Top X%"（越小越好）
        beat_pct    击败了百分之多少的人类
    """
    hs = sorted((float(h) for h in human_scores), reverse=higher_is_better)
    n = len(hs)
    if n == 0:
        return {"rank": None, "n": 0, "top_pct": None, "beat_pct": None,
                "note": "no human reference distribution"}

    if higher_is_better:
        rank = 1 + sum(1 for h in hs if h > score)
        beat = sum(1 for h in hs if h < score)
    else:
        rank = 1 + sum(1 for h in hs if h < score)
        beat = sum(1 for h in hs if h > score)

    return {
        "rank": rank,
        "n": n,
        "top_pct": round(100.0 * rank / n, 2),
        "beat_pct": round(100.0 * beat / n, 2),
    }


def performance_elo(
    score: float,
    human_scores: Sequence[float],
    higher_is_better: bool = True,
    base: float = 1500.0,
) -> Dict[str, Any]:
    """把分数转成 Elo-like Performance（ALE-Bench 的归一化口径）。

    做法：先算该分数击败人类的比例 p（平局按一半计），
    再用 Elo 期望胜率的反函数换算等级分：

        E = 1 / (1 + 10^((Rb - Ra) / 400))
      ⇒ Ra - Rb = 400 * log10(E / (1 - E))

    这样同一个分数在不同人类分布下会得到不同的 Performance，
    且天然压缩两端（Top 1% 和 Top 0.1% 的差距不会被线性放大）。
    """
    hs = [float(h) for h in human_scores]
    n = len(hs)
    if n == 0:
        return {"elo": None, "percentile": None, "n": 0,
                "note": "no human reference distribution"}

    win = sum(1 for h in hs if (score > h if higher_is_better else score < h))
    tie = sum(1 for h in hs if h == score)
    p = (win + 0.5 * tie) / n

    # 夹到 (0,1) 内：全员第一也不给无穷大 Elo，用半格作为上界
    p = _clamp(p, 1.0 / (2.0 * n), 1.0 - 1.0 / (2.0 * n))

    elo = base + 400.0 * math.log10(p / (1.0 - p))
    return {
        "elo": round(elo, 1),
        "percentile": round(p, 4),
        "n": n,
        "rank": rank_percentile(score, hs, higher_is_better)["rank"],
    }


# --------------------------------------------------------------------------
# 2. 时间轴：多给时间还值不值
# --------------------------------------------------------------------------

def long_horizon_curve(
    points: Sequence[Tuple[float, float]],
    budget_unit: str = "seconds",
) -> Dict[str, Any]:
    """时间—分数曲线的边际收益分析。

    `points` = [(budget, score), ...]，预算可以是秒、步数、token 数，
    只要单调即可（单位写进 `budget_unit` 供报告使用）。

    返回每段：
        delta_score      这一段的绝对涨分
        per_doubling     预算每翻一倍能涨多少（**核心指标**）
        efficiency       每单位预算涨多少

    `per_doubling` 是判断"还值不值得加预算"的关键：
    ALE-Bench 的曲线从 1h→1w 涨了 33 分，但后段每翻倍只涨 4.5 分。
    """
    pts = sorted(((float(b), float(s)) for b, s in points), key=lambda x: x[0])
    if len(pts) < 2:
        return {"n_points": len(pts), "segments": [],
                "note": "need >= 2 budget points"}

    segments: List[Dict[str, Any]] = []
    for (b0, s0), (b1, s1) in zip(pts, pts[1:]):
        db = b1 - b0
        ds = s1 - s0
        doublings = math.log2(b1 / b0) if b0 > 0 and b1 > 0 else 0.0
        segments.append({
            "from": b0,
            "to": b1,
            "delta_score": _r2(ds),
            "per_doubling": _r2(ds / doublings) if doublings > 1e-9 else None,
            "efficiency": _r2(ds / db) if db > 1e-9 else None,
        })

    gains = [s["delta_score"] for s in segments if s["delta_score"] is not None]
    pd = [s["per_doubling"] for s in segments if s["per_doubling"] is not None]

    return {
        "budget_unit": budget_unit,
        "n_points": len(pts),
        "segments": segments,
        "total_gain": _r2(pts[-1][1] - pts[0][1]),
        "last_gain": _r2(gains[-1]) if gains else None,
        "last_per_doubling": _r2(pd[-1]) if pd else None,
        "monotonic": all(g >= -1e-9 for g in gains),
        "diminishing_returns": bool(len(pd) >= 2 and pd[-1] < pd[0]),
    }


def saturation_check(
    points: Sequence[Tuple[float, float]],
    near_asymptote: float = 0.02,
    min_points: int = 3,
) -> Dict[str, Any]:
    """这套题还剩多少上升空间？（ALE-Bench "开放式上限"的可测量版本）

    用三点法拟合饱和曲线 s(t) = A - B·r^t：

        令 q = r^h = (s3 - s2) / (s2 - s1)
        则 A = s1 + (s2 - s1) / (1 - q)

    三点按 (min, mid, max) 取，mid 处分数用线性插值补齐（不要求等距采样）。

    返回：
        asymptote   估计的天花板 A；无法拟合时为 None
        headroom   A - 当前最高分（还能涨多少）
        headroom_ratio  headroom / A
        saturated   是否已贴到天花板
        verdict     still-climbing / plateauing / saturated / insufficient_data
                    / not-saturating（还在加速，反而说明预算给少了）
    """
    pts = sorted(((float(b), float(s)) for b, s in points), key=lambda x: x[0])
    curve = long_horizon_curve(pts)

    if len(pts) < min_points:
        return {"asymptote": None, "headroom": None, "headroom_ratio": None,
                "saturated": None, "verdict": "insufficient_data",
                "n_points": len(pts), "curve": curve,
                "note": f"need >= {min_points} budget points to fit an asymptote"}

    t1, t3 = pts[0][0], pts[-1][0]
    s1, s3 = pts[0][1], pts[-1][1]
    t2 = 0.5 * (t1 + t3)

    # mid 处线性插值
    s2 = None
    for (b0, s0), (b1, s1_) in zip(pts, pts[1:]):
        if b0 <= t2 <= b1 and b1 > b0:
            s2 = s0 + (s1_ - s0) * (t2 - b0) / (b1 - b0)
            break
    if s2 is None:
        mid = pts[len(pts) // 2]
        t2, s2 = mid[0], mid[1]

    d1, d2 = s2 - s1, s3 - s2
    best = max(s for _, s in pts)

    # 增量非正 → 根本没在涨，谈不了饱和
    if d1 <= 1e-12:
        return {"asymptote": _r2(best), "headroom": 0.0, "headroom_ratio": 0.0,
                "saturated": True, "verdict": "saturated",
                "n_points": len(pts), "curve": curve,
                "note": "no measurable gain across budget points"}

    q = d2 / d1
    # q >= 1 说明还在加速（或线性），没有可拟合的天花板
    if q >= 1.0:
        return {"asymptote": None, "headroom": None, "headroom_ratio": None,
                "saturated": False, "verdict": "not-saturating",
                "n_points": len(pts), "curve": curve,
                "note": "gains not decelerating — budget is probably too small"}

    A = s1 + d1 / (1.0 - q)
    # 天花板不应低于已观测到的最高分
    A = max(A, best)
    headroom = A - best
    ratio = headroom / A if A > 1e-12 else 0.0
    # 阈值按量级自适应：near_asymptote 默认按 0–1 归一化分数标定，
    # 若分数是 0–100 制（ALE-Bench 就是），要同比例放大，否则会误判为未饱和。
    scale = max(1.0, abs(best))
    saturated = headroom <= near_asymptote * scale

    if saturated:
        verdict = "saturated"
    elif ratio <= 0.10:
        verdict = "plateauing"
    else:
        verdict = "still-climbing"

    return {
        "asymptote": _r2(A),
        "headroom": _r2(headroom),
        "headroom_ratio": _r2(ratio),
        "saturated": saturated,
        "verdict": verdict,
        "n_points": len(pts),
        "decay_q": _r2(q),
        "curve": curve,
    }


# --------------------------------------------------------------------------
# 3. 成本轴：帕累托前沿
# --------------------------------------------------------------------------

def cost_quality_frontier(
    records: Sequence[Dict[str, Any]],
    name_key: str = "name",
    cost_key: str = "cost",
    score_key: str = "score",
    higher_is_better: bool = True,
) -> Dict[str, Any]:
    """成本—质量帕累托前沿（ALE-Bench 的成本轴）。

    只报分数不报成本是评测报告最常见的失真：
    ALE-Agent 1879 分但 $100.33/题，OpenHands 905 分只要 $3.25/题 ——
    谁更好取决于预算，不取决于分数。

    返回每个方案的：
        dominated      是否被别人支配（存在分数不差且更便宜的）
        on_frontier    是否在帕累托前沿上
        efficiency     每单位成本的得分（性价比）
    """
    items = []
    for r in records:
        cost = float(r.get(cost_key, 0.0))
        score = float(r.get(score_key, 0.0))
        items.append({
            "name": r.get(name_key, "?"),
            "cost": cost,
            "score": score,
            "efficiency": _r2(score / cost) if cost > 1e-12 else None,
        })

    def _beats(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        """a 是否支配 b（分数不更差 且 成本更低，且至少一个严格更优）。"""
        if higher_is_better:
            s_ok = a["score"] >= b["score"]
            s_strict = a["score"] > b["score"]
        else:
            s_ok = a["score"] <= b["score"]
            s_strict = a["score"] < b["score"]
        c_ok = a["cost"] <= b["cost"]
        c_strict = a["cost"] < b["cost"]
        return s_ok and c_ok and (s_strict or c_strict)

    for a in items:
        a["dominated"] = any(
            _beats(b, a) for b in items
            if b["name"] != a["name"]
            or b["cost"] != a["cost"] or b["score"] != a["score"]
        )
        a["on_frontier"] = not a["dominated"]

    front = sorted(
        [i for i in items if i["on_frontier"]], key=lambda x: x["cost"]
    )
    return {
        "n": len(items),
        "frontier": [i["name"] for i in front],
        "dominated": [i["name"] for i in items if i["dominated"]],
        "items": sorted(items, key=lambda x: (-x["score"] if higher_is_better else x["score"])),
        "best_efficiency": max(
            (i for i in items if i["efficiency"] is not None),
            key=lambda x: x["efficiency"], default=None,
        ),
    }


def budget_report(
    records: Sequence[Dict[str, Any]],
    human_scores: Optional[Sequence[float]] = None,
    **kw: Any,
) -> Dict[str, Any]:
    """一份能直接贴进论文表格的汇总：分数 + 成本 + 性价比 + 人类分位。

    `human_scores` 给了才算 Performance 列，没给就如实留空。
    """
    fr = cost_quality_frontier(records, **kw)
    for it in fr["items"]:
        if human_scores:
            it["performance"] = performance_elo(it["score"], human_scores)
            it["top_pct"] = rank_percentile(it["score"], human_scores)["top_pct"]
        else:
            it["performance"] = None
            it["top_pct"] = None
    fr["has_human_anchor"] = bool(human_scores)
    return fr
