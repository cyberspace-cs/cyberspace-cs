"""环境质量四维评价 + 多样性度量。

理论依据：中科院自动化所综述 arXiv:2606.12191《Agentic Environment Engineering》
把合成环境的评价分为四个维度：

    correctness  正确性  —— 题可解吗？判分对吗？
    diversity    多样性  —— 池子是不是全是同一类题？
    complexity   复杂性  —— 难度分布合理吗？（天花板 / 地板效应）
    fidelity     忠实度  —— 合成题像真实题吗？

以及 AWM (Agent World Model, UNC + Snowflake, arXiv:2602.10090, ICML'26) 的两条工程指标：
    blocked rate  —— 连黄金解答都跑不通的废题占比
    category cap  —— 单类别占比上限，防止池子崩塌（mode collapse）

设计原则：
1. 零外部依赖。不装 numpy / sklearn / embedding 模型也能跑完整流程，
   拿到 embedding 时自动升级为更准的语义多样性。
2. 度量本身要能被证伪。每个分数都返回它依赖的样本量与降级标志，
   不允许"算不出就悄悄给个好看的数"。

用法：
    from engine.analytics import env_quality_report
    report = env_quality_report(tasks)
    print(report["verdict"])
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "DiversityReport",
    "QualityReport",
    "diversity_score",
    "structural_signature",
    "dedup_by_embedding",
    "category_distribution",
    "category_cap_check",
    "blocked_rate",
    "difficulty_histogram",
    "ceiling_floor_check",
    "env_quality_report",
]


# --------------------------------------------------------------------------
# 0. 工具
# --------------------------------------------------------------------------

def _shannon_entropy(counts: Iterable[float]) -> float:
    """香农熵（自然对数）。返回 0 表示分布完全集中（最差多样性）。"""
    vals = [c for c in counts if c > 0]
    total = sum(vals)
    if not total:
        return 0.0
    return -sum((c / total) * math.log(c / total) for c in vals)


def _normalised_entropy(counts: Iterable[float]) -> float:
    """熵归一化到 [0,1]：1 = 完全均匀，0 = 全部集中在一类。

    除以 log(k)，k = 类别数。这样不同类别数的池子可以横向比较。
    """
    vals = [c for c in counts if c > 0]
    k = len(vals)
    if k <= 1:
        return 0.0
    return _shannon_entropy(vals) / math.log(k)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------
# 1. 结构签名：无 embedding 时的多样性代理
# --------------------------------------------------------------------------

# 从一段源码/任务描述里抽取的结构特征词。用于构造"形状指纹"。
_STRUCT_PATTERNS: List[Tuple[str, str]] = [
    ("modifier", r"\b(onlyOwner|onlyRole|nonReentrant|payable|view|pure|external|internal)\b"),
    ("call",     r"\b(call|delegatecall|staticcall|send|transfer)\s*(\{|\()"),
    ("loop",     r"\b(for|while)\s*\("),
    ("branch",   r"\b(if|require|assert|revert)\b"),
    ("math",     r"[\+\-\*/]\s*=?|%\s*=?|\*\*"),
    ("storage",  r"\b(mapping|SSTORE|sload)\b|\bmapping\s*\("),
    ("event",    r"\bemit\s+\w+"),
    ("modifier_def", r"\bmodifier\s+\w+"),
    ("interface", r"\b(interface|abstract\s+contract)\b"),
    ("assembly", r"\bassembly\s*\{"),
]

# 审计赛道的结构特征（账套 / 资金流 / 底稿）
_AUDIT_PATTERNS: List[Tuple[str, str]] = [
    ("voucher",  r"凭证|凭证明细|voucher"),
    ("ledger",   r"总账|明细账|ledger|科目余额"),
    ("recon",    r"勾稽|对账|调节表|reconcil"),
    ("fundflow", r"资金流|拨付|转移支付|专项"),
    ("law",      r"第\s*\d+\s*条|条例|办法|规定"),
    ("evidence", r"审计证据|底稿|工作底稿|函证"),
    ("ratio",    r"比率|周转|毛利率|费用率"),
    ("period",   r"跨期|截止|期后|截止性"),
]


def structural_signature(item: Dict[str, Any]) -> Dict[str, float]:
    """把一个任务/样本压成结构指纹（词频向量）。

    对符号合成的环境，结构特征比 embedding 更准也更便宜：
    雷型组合、控制流形状、业务语义标记，直接决定了这道题"长什么样"。

    返回 {特征名: 归一化频次}，可直接喂给 diversity_score。
    """
    blob_parts: List[str] = []
    for key in ("source", "code", "contract", "instruction", "description",
                "prompt", "content", "text"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            blob_parts.append(v)

    # 结构化字段也算进来（雷型、算子、难度）
    for key in ("vuln_type", "vuln_types", "operators", "tags", "category"):
        v = item.get(key)
        if isinstance(v, str):
            blob_parts.append(v)
        elif isinstance(v, (list, tuple)):
            blob_parts.extend(str(x) for x in v)

    blob = "\n".join(blob_parts)
    if not blob.strip():
        return {}

    patterns = _STRUCT_PATTERNS + _AUDIT_PATTERNS
    length = max(len(blob), 1)
    sig: Dict[str, float] = {}
    for name, pat in patterns:
        n = len(re.findall(pat, blob))
        if n:
            # 用 sqrt 压制长文件的高频词，让指纹反映"形状"而非"体积"
            sig[name] = math.sqrt(n) / math.sqrt(length / 512.0 + 1.0)

    # 离散标签直接进入指纹（雷型是最强的区分信号）
    vt = item.get("vuln_type") or item.get("category")
    if isinstance(vt, str) and vt:
        sig["vuln:" + vt] = 1.0
    elif isinstance(vt, (list, tuple)):
        for t in vt:
            sig["vuln:" + str(t)] = 1.0

    op = item.get("operators")
    if isinstance(op, (list, tuple)):
        for o in op:
            sig["op:" + str(o)] = 1.0

    return sig


# --------------------------------------------------------------------------
# 2. 多样性
# --------------------------------------------------------------------------

class DiversityReport(dict):
    """多样性报告。dict 子类，方便直接 json 序列化。"""

    @property
    def verdict(self) -> str:
        s = self.get("score", 0.0)
        if s >= 0.75:
            return "healthy"
        if s >= 0.5:
            return "narrow"
        if s >= 0.25:
            return "collapsing"
        return "collapsed"


def diversity_score(
    tasks: Sequence[Dict[str, Any]],
    embed_fn: Optional[Callable[[str], Sequence[float]]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> DiversityReport:
    """综合多样性分 ∈ [0,1]。

    三个子信号（默认权重 4:3:3）：
      - semantic  语义覆盖度：有 embed_fn 时用最远点采样估计嵌入空间的铺开程度；
                  无 embed_fn 时降级为结构指纹的同一算法（仍有效，只是语义层弱一些）
      - category  类别均衡度：类别分布的归一化熵
      - structural 结构离散度：结构指纹两两距离的均值

    返回字段里带 `degraded`，明确告诉你哪些信号是降级算出来的。
    """
    weights = weights or {"semantic": 0.4, "category": 0.3, "structural": 0.3}
    n = len(tasks)
    if n == 0:
        return DiversityReport(score=0.0, n=0, degraded=True,
                               note="empty pool")

    # --- (a) 向量化 ---
    degraded = embed_fn is None
    vecs: List[List[float]] = []
    keys: List[str] = []

    if embed_fn is not None:
        for t in tasks:
            text = "\n".join(
                str(t.get(k, "")) for k in
                ("instruction", "description", "source", "code", "content", "text")
                if t.get(k)
            )
            try:
                v = list(embed_fn(text))
            except Exception:
                v = []
            vecs.append([float(x) for x in v] if v else None)  # type: ignore[arg-type]
    else:
        sigs = [structural_signature(t) for t in tasks]
        keys = sorted({k for s in sigs for k in s})
        for s in sigs:
            vecs.append([float(s.get(k, 0.0)) for k in keys])

    valid = [v for v in vecs if v and any(x != 0 for x in v)]
    if len(valid) < 2:
        semantic = 0.0
    else:
        semantic = _spread_score(valid)

    # --- (b) 类别均衡 ---
    dist = category_distribution(tasks)
    category = _normalised_entropy(list(dist.values())) if dist else 0.0

    # --- (c) 结构离散度：结构指纹两两平均距离 ---
    if len(valid) < 2:
        structural = 0.0
    else:
        # 限制计算量：>80 个样本时抽样 pairwise，避免 O(n^2) 爆炸
        step = max(1, len(valid) // 80)
        sample = valid[::step]
        tot, cnt = 0.0, 0
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                tot += 1.0 - _cosine(sample[i], sample[j])
                cnt += 1
        structural = _clamp(tot / cnt) if cnt else 0.0

    score = _clamp(
        weights["semantic"] * semantic
        + weights["category"] * category
        + weights["structural"] * structural
    )

    return DiversityReport(
        score=round(score, 4),
        n=n,
        semantic=round(semantic, 4),
        category=round(category, 4),
        structural=round(structural, 4),
        n_categories=len(dist),
        distribution=dist,
        degraded=degraded,
        note=("embedding 未提供，语义覆盖度降级为结构指纹计算"
              if degraded else "embedding 已接入"),
    )


def _spread_score(vecs: List[List[float]]) -> float:
    """用最远点采样（farthest-point sampling）估计向量集合在空间里的铺开程度。

    直觉：从随机一点出发，每次挑离已选集合最远的点。
    如果池子扎堆，最远距离会迅速衰减到 0；如果铺得开，距离衰减慢。

    返回 ∈ [0,1] 的铺开度。
    """
    n = len(vecs)
    if n < 2:
        return 0.0
    step = max(1, n // 40)          # 抽 ≤40 个点，控制 O(n·k)
    pts = vecs[::step][:40]
    k = len(pts)
    if k < 2:
        return 0.0

    selected = [0]
    dists = [1.0 - _cosine(pts[0], pts[i]) for i in range(k)]
    radii: List[float] = []
    for _ in range(min(k - 1, 12)):
        far = max(range(k), key=lambda i: dists[i])
        radii.append(dists[far])
        if dists[far] <= 1e-9:
            break
        selected.append(far)
        for i in range(k):
            d = 1.0 - _cosine(pts[far], pts[i])
            if d < dists[i]:
                dists[i] = d

    if not radii:
        return 0.0
    # 覆盖度 = 后半段半径 / 首半径。铺得开 → 衰减慢 → 比值高
    first = radii[0] if radii[0] > 1e-9 else 1e-9
    tail = sum(radii[len(radii) // 2:]) / max(len(radii) - len(radii) // 2, 1)
    return _clamp(tail / first)


def category_distribution(tasks: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """按 vuln_type / category / operators 统计类别分布。"""
    c: Counter = Counter()
    for t in tasks:
        key = t.get("vuln_type") or t.get("category") or t.get("task_type")
        if isinstance(key, (list, tuple)):
            for x in key:
                c[str(x)] += 1
        elif key:
            c[str(key)] += 1
        else:
            ops = t.get("operators")
            if isinstance(ops, (list, tuple)) and ops:
                c["+".join(str(o) for o in ops)] += 1
            else:
                c["<unlabeled>"] += 1
    return dict(c.most_common())


def category_cap_check(
    tasks: Sequence[Dict[str, Any]],
    cap: float = 0.4,
) -> Dict[str, Any]:
    """单类别占比上限检查（AWM 的防崩塌手段）。

    cap=0.4 表示任何一类不得超过池子的 40%。
    """
    dist = category_distribution(tasks)
    total = sum(dist.values()) or 1
    over = {k: round(v / total, 4) for k, v in dist.items() if v / total > cap}
    return {
        "cap": cap,
        "n": total,
        "violations": over,
        "ok": not over,
        "top_share": round(max(dist.values()) / total, 4) if dist else 0.0,
    }


def dedup_by_embedding(
    tasks: Sequence[Dict[str, Any]],
    embed_fn: Callable[[str], Sequence[float]],
    threshold: float = 0.95,
) -> List[int]:
    """按余弦相似度去重，返回**保留下来**的下标。

    threshold=0.95 表示相似度 > 0.95 的后续样本视为重复，丢弃。
    有 embed_fn 时用语义；没有就传 structural_signature 的向量化版本。
    """
    kept: List[int] = []
    kept_vecs: List[List[float]] = []
    for idx, t in enumerate(tasks):
        text = "\n".join(
            str(t.get(k, "")) for k in
            ("instruction", "description", "source", "code", "content", "text")
            if t.get(k)
        )
        try:
            v = [float(x) for x in embed_fn(text)]
        except Exception:
            # 生成失败的样本保守保留，不静默丢弃
            kept.append(idx)
            continue
        if not v:
            kept.append(idx)
            continue
        dup = False
        for kv in kept_vecs:
            if _cosine(kv, v) >= threshold:
                dup = True
                break
        if not dup:
            kept.append(idx)
            kept_vecs.append(v)
    return kept


# --------------------------------------------------------------------------
# 3. 正确性 / 复杂性 / 忠实度
# --------------------------------------------------------------------------

def blocked_rate(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """废题率：连黄金解答都跑不通的题占比（AWM 的关键可靠性指标）。

    results 每项形如：
        {"task_id": ..., "gold_passed": true/false, "reason": ...}

    黄金解答自己都过不了 → 这道题的信号不可信，必须剔除。
    """
    n = len(results)
    if n == 0:
        return {"n": 0, "blocked": 0, "rate": 0.0, "blocked_ids": []}
    bad = [r.get("task_id") for r in results if not r.get("gold_passed", False)]
    return {
        "n": n,
        "blocked": len(bad),
        "rate": round(len(bad) / n, 4),
        "blocked_ids": bad,
        "verdict": "ok" if len(bad) / n <= 0.05 else "too_many_blocked",
    }


def difficulty_histogram(
    tasks: Sequence[Dict[str, Any]],
    bins: int = 5,
) -> Dict[str, Any]:
    """难度分布直方图。查天花板 / 地板效应的第一手段。

    难度取值：优先实测难度（0..1，越大越难），退化到手填 difficulty 字段。
    """
    vals: List[float] = []
    for t in tasks:
        d = t.get("empirical_difficulty")
        if d is None:
            d = t.get("difficulty")
        if d is None:
            continue
        try:
            dv = float(d)
        except (TypeError, ValueError):
            continue
        if dv > 1.0:      # 手填档位（如 1..5）归一化
            dv = dv / 5.0
        vals.append(_clamp(dv))

    if not vals:
        return {"n": 0, "bins": [], "has_data": False}

    edges = [i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for v in vals:
        i = min(int(v * bins), bins - 1)
        counts[i] += 1
    return {
        "n": len(vals),
        "has_data": True,
        "mean": round(sum(vals) / len(vals), 4),
        "bins": [
            {"range": [round(edges[i], 2), round(edges[i + 1], 2)], "count": counts[i]}
            for i in range(bins)
        ],
    }


def ceiling_floor_check(
    scores: Sequence[float],
    ceiling: float = 0.95,
    floor: float = 0.05,
) -> Dict[str, Any]:
    """天花板 / 地板效应检查。

    传进来的是**各模型在该题上的得分序列**（不是全局分数）：
    如果所有模型都接近满分 → 天花板；都接近 0 → 地板。
    两种情况下这道题对排序的贡献都是 0。
    """
    if not scores:
        return {"n": 0, "verdict": "no_data"}
    n = len(scores)
    hi = sum(1 for s in scores if s >= ceiling)
    lo = sum(1 for s in scores if s <= floor)
    if hi == n:
        verdict = "ceiling"
    elif lo == n:
        verdict = "floor"
    elif hi / n >= 0.8:
        verdict = "near_ceiling"
    elif lo / n >= 0.8:
        verdict = "near_floor"
    else:
        verdict = "ok"
    return {
        "n": n,
        "ceiling_hits": hi,
        "floor_hits": lo,
        "spread": round(max(scores) - min(scores), 4),
        "verdict": verdict,
    }


# --------------------------------------------------------------------------
# 4. 四维总报告
# --------------------------------------------------------------------------

class QualityReport(dict):
    @property
    def verdict(self) -> str:
        dims = self.get("dimensions", {})
        if not dims:
            return "no_data"
        missing = [k for k, v in dims.items()
                   if v.get("score") is None]
        scored = [v["score"] for v in dims.values() if v.get("score") is not None]
        if not scored:
            return "no_data"
        avg = sum(scored) / len(scored)
        if avg >= 0.75 and not missing:
            base = "healthy"
        elif avg >= 0.5:
            base = "acceptable"
        elif avg >= 0.25:
            base = "weak"
        else:
            base = "unusable"
        # 有维度没测出来时，不允许给出"无保留"的判定
        if missing:
            return f"{base}(incomplete: {len(missing)} dims unmeasured)"
        return base


def env_quality_report(
    tasks: Sequence[Dict[str, Any]],
    *,
    gold_results: Optional[Sequence[Dict[str, Any]]] = None,
    per_task_scores: Optional[Dict[str, Sequence[float]]] = None,
    embed_fn: Optional[Callable[[str], Sequence[float]]] = None,
    reference_tasks: Optional[Sequence[Dict[str, Any]]] = None,
    cap: float = 0.4,
) -> QualityReport:
    """四维环境体检报告。

    参数
    ----
    tasks            题目/环境列表
    gold_results     黄金解答自测结果（算 blocked rate，正确性维）
    per_task_scores  {task_id: [各模型得分]}（算天花板/地板，复杂性维）
    embed_fn         可选，文本 → 向量，接入后语义多样性更准
    reference_tasks  可选，**真实**任务锚定集，用于算忠实度
    cap              单类别占比上限

    返回 QualityReport（dict 子类，可直接 json.dumps）。
    """
    div = diversity_score(tasks, embed_fn=embed_fn)
    capchk = category_cap_check(tasks, cap=cap)
    hist = difficulty_histogram(tasks)

    # 正确性维
    if gold_results is not None:
        blk = blocked_rate(gold_results)
        # 废题率 0 → 1.0；>=20% → 0
        correctness = _clamp(1.0 - blk["rate"] / 0.20)
        correctness_detail = {"blocked": blk, "score": round(correctness, 4)}
    else:
        correctness_detail = {
            "score": None,
            "note": "未提供 gold_results，正确性维无法定量（请让黄金解答自测一遍）",
        }

    # 复杂性维：难度分布是否铺开 + 有没有天花板/地板
    if hist.get("has_data"):
        bins = [b["count"] for b in hist["bins"]]
        # 两个因子相乘：
        #   evenness  —— 已占用档位上的分布是否均匀
        #   occupancy —— 占用了多少档（只占 2/5 档不该拿高分，
        #                因为难度梯度根本没铺开，天花板/地板风险仍在）
        evenness = _normalised_entropy(bins)
        occupancy = sum(1 for c in bins if c > 0) / len(bins)
        spread = evenness * occupancy
        cf: Dict[str, Any] = {}
        if per_task_scores:
            bad = [tid for tid, ss in per_task_scores.items()
                   if ceiling_floor_check(list(ss))["verdict"] in ("ceiling", "floor")]
            cf = {"flat_tasks": bad, "n_flat": len(bad)}
            spread *= _clamp(1.0 - len(bad) / max(len(per_task_scores), 1))
        complexity_detail = {
            "score": round(_clamp(spread), 4),
            "evenness": round(evenness, 4),
            "occupancy": round(occupancy, 4),
            "histogram": hist,
            "ceiling_floor": cf,
        }
    else:
        complexity_detail = {
            "score": None,
            "note": "任务缺 difficulty / empirical_difficulty 字段",
        }

    # 忠实度维：合成池 vs 真实锚定集的分布距离
    if reference_tasks:
        fid = _fidelity_score(tasks, reference_tasks)
        fidelity_detail = fid
    else:
        fidelity_detail = {
            "score": None,
            "note": "未提供 reference_tasks（真实任务锚定集），忠实度无法度量。"
                    "这是当前最大盲区：合成题刷分不等于真实能力。",
        }

    dims = {
        "correctness": correctness_detail,
        "diversity": {"score": div["score"], "detail": dict(div), "category_cap": capchk},
        "complexity": complexity_detail,
        "fidelity": fidelity_detail,
    }

    actions: List[str] = []
    if correctness_detail.get("score") is None:
        actions.append("跑一遍黄金解答自测，补上 blocked rate")
    elif correctness_detail["score"] < 0.8:
        actions.append("废题过多，检查算子与验证器")
    if div["score"] < 0.5:
        actions.append("多样性不足，补充算子/雷型，或对池子做去重")
    if not capchk["ok"]:
        actions.append("类别分布触顶：%s" % ", ".join(capchk["violations"].keys()))
    if complexity_detail.get("score") is not None and complexity_detail["score"] < 0.5:
        actions.append("难度分布集中，加难或降难以铺开梯度")
    if fidelity_detail.get("score") is None:
        actions.append("尽快建立真实任务锚定集（忠实度是外推能力的前提）")

    return QualityReport(
        n_tasks=len(tasks),
        dimensions=dims,
        actions=actions,
    )


def _fidelity_score(
    tasks: Sequence[Dict[str, Any]],
    reference: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """忠实度：合成池与真实锚定集的分布距离。

    用**类别分布 + 结构指纹质心**两个层面比，取较严格的那个。
    距离 → 分数：0 距离 = 1.0，距离 1.0 = 0 分。
    """
    # (a) 类别分布的 Jensen-Shannon 距离
    ds = category_distribution(tasks)
    dr = category_distribution(reference)
    keys = sorted(set(ds) | set(dr))
    ts = sum(ds.values()) or 1
    tr = sum(dr.values()) or 1
    p = [ds.get(k, 0) / ts for k in keys]
    q = [dr.get(k, 0) / tr for k in keys]
    js = _js_distance(p, q)

    # (b) 结构指纹质心的余弦距离
    cs = _centroid([structural_signature(t) for t in tasks])
    cr = _centroid([structural_signature(t) for t in reference])
    common = sorted(set(cs) | set(cr))
    vs = [cs.get(k, 0.0) for k in common]
    vr = [cr.get(k, 0.0) for k in common]
    struct_d = 1.0 - _cosine(vs, vr)

    dist = max(js, struct_d)
    return {
        "score": round(_clamp(1.0 - dist), 4),
        "category_js_distance": round(js, 4),
        "structural_distance": round(struct_d, 4),
        "n_synthetic": len(tasks),
        "n_reference": len(reference),
        "note": "分数低说明合成题与真实题长得不像，评测分数无法外推",
    }


def _centroid(sigs: Sequence[Dict[str, float]]) -> Dict[str, float]:
    if not sigs:
        return {}
    acc: Dict[str, float] = {}
    for s in sigs:
        for k, v in s.items():
            acc[k] = acc.get(k, 0.0) + v
    n = len(sigs)
    return {k: v / n for k, v in acc.items()}


def _js_distance(p: Sequence[float], q: Sequence[float]) -> float:
    """Jensen-Shannon 距离（开方后的 JS 散度），∈ [0,1]。"""
    if not p or not q or len(p) != len(q):
        return 1.0
    sp, sq = sum(p), sum(q)
    if sp == 0 or sq == 0:
        return 1.0
    p = [x / sp for x in p]
    q = [x / sq for x in q]
    m = [0.5 * (a + b) for a, b in zip(p, q)]

    def _kl(a: Sequence[float], b: Sequence[float]) -> float:
        s = 0.0
        for x, y in zip(a, b):
            if x > 0 and y > 0:
                s += x * math.log(x / y)
        return s

    js = 0.5 * _kl(p, m) + 0.5 * _kl(q, m)
    # JS 散度上界 ln2，归一化
    return _clamp(math.sqrt(max(js, 0.0)) / math.sqrt(math.log(2)))
