"""难度校准、区分度与抗污染性指标。

背景（见 docs/05-ideas.md 的 I1 / I6）：
  - 现有 AI Filter 只做 trivial / differentiating 二分类，太粗糙；
  - 现有 benchmark 是单次采样，没有方差，结论站不住；
  - 公开 benchmark 会被训练语料污染，但我们"可再生"的题不会——
    这件事需要被**量化**，否则只是一句口号。

本模块提供四组指标（全部零依赖）：
  1. pass_rate / item_difficulty    —— 题目实测难度（替代手填的 difficulty 字段）
  2. item_discrimination            —— 区分度（能不能把强弱模型分开）
  3. fit_rasch                      —— 简化 IRT（1PL/Rasch）拟合，得到同一把尺子上的
                                       题目难度 b_i 与模型能力 theta_j
  4. contamination_resistance       —— CRS 抗污染分：换 seed 重生成后分数是否稳定
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


# ---------------------------------------------------------------------------
# 1. 实测难度
# ---------------------------------------------------------------------------

def pass_rate(scores: Sequence[float], threshold: float = 1.0) -> float:
    """通过率：scores 中 >= threshold 的比例（scores 可以是 0/1，也可以是 F1 等连续分）。"""
    scores = list(scores or [])
    if not scores:
        return 0.0
    return sum(1 for s in scores if s >= threshold) / len(scores)


def item_difficulty(scores: Sequence[float], threshold: float = 1.0) -> float:
    """题目难度 ∈ [0,1]，越大越难。定义为 1 - 平均通过率。

    用手填的 difficulty=1/2 无法跨题比较；这个值是实测的，可用于排序与选题。
    """
    return round(1.0 - pass_rate(scores, threshold), 4)


# ---------------------------------------------------------------------------
# 2. 区分度（经典测验学：上下 27% 分组）
# ---------------------------------------------------------------------------

def item_discrimination(
    abilities: Sequence[float],
    scores: Sequence[float],
    group_frac: float = 0.27,
) -> float:
    """区分度 D = 高能力组通过率 - 低能力组通过率 ∈ [-1, 1]。

    abilities: 每个作答者的能力代理值（可用该模型在本套题上的总分）
    scores:    对应作答者在这道题上的得分（0/1 或连续分）
    D > 0.3 为好题；D <= 0 说明这道题要么太难要么太易，或本身有歧义。
    """
    pairs = sorted(zip(list(abilities or []), list(scores or [])), key=lambda x: x[0])
    if not pairs:
        return 0.0
    k = max(1, int(round(len(pairs) * group_frac)))
    if 2 * k >= len(pairs):
        k = max(1, len(pairs) // 2 - 1) if len(pairs) >= 4 else 1
    low = [s for _, s in pairs[:k]]
    high = [s for _, s in pairs[-k:]]
    return round(statistics.fmean(high) - statistics.fmean(low), 4)


# ---------------------------------------------------------------------------
# 3. 简化 IRT（Rasch / 1PL）
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


@dataclass
class RaschResult:
    """Rasch 模型拟合结果。同一把尺子上：能力 theta 与难度 b 可直接相减。"""

    ability: Dict[str, float] = field(default_factory=dict)   # 模型/作答者 -> theta
    difficulty: Dict[str, float] = field(default_factory=dict)  # 题目 -> b
    iterations: int = 0
    log_likelihood: float = 0.0

    def prob(self, who: str, item: str) -> float:
        return _sigmoid(self.ability.get(who, 0.0) - self.difficulty.get(item, 0.0))

    def most_informative_items(self, who: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """对某个作答者信息量最大的题：难度最接近其能力的题信息量最大。"""
        theta = self.ability.get(who, 0.0)
        ranked = sorted(self.difficulty.items(), key=lambda kv: abs(kv[1] - theta))
        return ranked[:top_k]


def fit_rasch(
    matrix: Mapping[Tuple[str, str], float],
    lr: float = 0.1,
    max_iter: int = 500,
    tol: float = 1e-5,
    l2: float = 1e-3,
) -> RaschResult:
    """拟合 1PL/Rasch 模型：P(答对) = sigmoid(theta_j - b_i)。

    matrix: {(who, item): 0/1 或 [0,1] 连续分}
    用交替梯度上升最大化对数似然，并在每轮做中心化（保证可识别性）。
    """
    if not matrix:
        return RaschResult()

    whos = sorted({w for w, _ in matrix})
    items = sorted({i for _, i in matrix})
    theta = {w: 0.0 for w in whos}
    b = {i: 0.0 for i in items}

    last_ll = -float("inf")
    it = 0
    for it in range(1, max_iter + 1):
        g_theta = {w: 0.0 for w in whos}
        g_b = {i: 0.0 for i in items}
        ll = 0.0
        for (w, i), y in matrix.items():
            y = min(1.0, max(0.0, float(y)))
            p = _sigmoid(theta[w] - b[i])
            p = min(1 - 1e-9, max(1e-9, p))
            resid = y - p
            g_theta[w] += resid
            g_b[i] -= resid
            ll += y * math.log(p) + (1 - y) * math.log(1 - p)

        for w in whos:
            theta[w] += lr * (g_theta[w] - l2 * theta[w])
        for i in items:
            b[i] += lr * (g_b[i] - l2 * b[i])

        # 中心化：让 b 的均值为 0（否则 theta 与 b 可同时平移，不可识别）
        mb = statistics.fmean(b.values()) if b else 0.0
        for i in items:
            b[i] -= mb
        for w in whos:
            theta[w] -= mb

        if abs(ll - last_ll) < tol:
            break
        last_ll = ll

    return RaschResult(
        ability={w: round(v, 4) for w, v in theta.items()},
        difficulty={i: round(v, 4) for i, v in b.items()},
        iterations=it,
        log_likelihood=round(last_ll, 4),
    )


# ---------------------------------------------------------------------------
# 4. 抗污染性 CRS
# ---------------------------------------------------------------------------

def contamination_resistance(
    score_original: float,
    score_regenerated: float,
    eps: float = 1e-9,
) -> float:
    """单题（或单模型）的抗污染分 CRS ∈ [0,1]，越大越可信。

    CRS = 1 - |S_orig - S_regen| / max(S_orig, eps)

    含义：同一算子换 seed 重新生成一道同分布新题，模型分数如果基本不变，
    说明它靠的是能力；如果大跌，说明它在原题上是靠"背"。
    """
    s0 = float(score_original or 0.0)
    s1 = float(score_regenerated or 0.0)
    denom = max(abs(s0), eps)
    return round(max(0.0, 1.0 - abs(s0 - s1) / denom), 4)


def crs_summary(pairs: Iterable[Tuple[float, float]]) -> Dict[str, float]:
    """多题/多模型的 CRS 汇总。

    pairs: [(S_orig, S_regen), ...]
    """
    vals = [contamination_resistance(a, b) for a, b in pairs or []]
    if not vals:
        return {"n": 0, "mean": 0.0, "min": 0.0, "std": 0.0}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "min": round(min(vals), 4),
        "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# 5. 重复实验的统计量（修"单次采样无统计力"）
# ---------------------------------------------------------------------------

def summarize_repeats(values: Sequence[float]) -> Dict[str, float]:
    """对同一 (模型, 样本) 的多次运行做统计汇总。"""
    vals = [float(v) for v in (values or [])]
    if not vals:
        return {"n": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
    }
