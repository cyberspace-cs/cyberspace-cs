"""ReportScorer：把审计报告对 ground truth 判 recall / precision / F1。

关键：precision 与 recall 同时计分，误报（FP）被惩罚，
从而防止“把所有问题全报一遍”刷高分。

提供两代打分器：
  - score_report   (v1)：类型集合匹配 + function token 交集。向后兼容，保留原签名。
  - score_report_v2(v2)：类型 + 位置 IoU + severity 加权 的三维打分，区分度更强。

v1 的历史缺陷（已修）：
  _TYPE_ALIASES 曾用子串匹配，导致 "non-reentrant"（意为“不可重入、是安全的”）
  命中别名 "reentrant" 被归一化成 reentrancy，进而把否定判断误判成 TP。
  现改为：先做否定检测，再用词边界正则匹配，并对 findings 去重。
"""

from __future__ import annotations

import re

from ..core.pipeline import ReportScorer


class AuditReportScorer(ReportScorer):
    name = "audit-report-scorer"

    def run(self, records):
        for rec in records:
            gt = set(rec.get("ground_truth_types", []))
            pred = set(rec.get("predicted_types", []))

            tp = len(gt & pred)
            fp = len(pred - gt)
            fn = len(gt - pred)

            recall = tp / (tp + fn) if (tp + fn) else 1.0
            precision = tp / (tp + fp) if (tp + fp) else 1.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall)
                else 0.0
            )

            rec["scores"] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "f1": round(f1, 4),
            }
        return records


# ---------------------------------------------------------------------------
# 类型归一化（v1 + v2 共用）
# ---------------------------------------------------------------------------

_TYPE_ALIASES = {
    "reentrancy": ["reentrancy", "reentrant", "re-entry", "reentry", "重入"],
    "access_control": [
        "access_control", "access control", "authorization", "unprotected",
        "onlyowner", "ownership", "权限", "访问控制", "missing access",
    ],
    "unchecked_call": ["unchecked_call", "unchecked call", "unhandled return", "unchecked return"],
    "tx_origin": ["tx_origin", "tx.origin", "txorigin"],
    "integer_error": ["integer", "overflow", "underflow"],
    "delegatecall": ["delegatecall"],
    "denial": ["denial", "dos", "denial of service"],
    "signature_replay": ["signature", "replay"],
}

# 否定/缓解语境：出现这些词说明模型在说“这里是安全的”，不是报漏洞
_NEGATION_PATTERNS = [
    r"\bnon[-\s]?reentr",      # non-reentrant
    r"\bnot\s+(?:vulnerable|exploitable|affected)",
    r"\bno\s+(?:vulnerability|issue|risk|reentrancy)",
    r"\bis\s+safe\b",
    r"\bsafe\s+from\b",
    r"\bmitigat(?:ed|es|ion)\b",
    r"\bprotected\s+(?:by|against)\b",
    r"\bguarded\s+by\b",
    r"\bprevent(?:s|ed)?\s+reentr",
    r"\bfollows?\s+(?:the\s+)?cei\b",   # 遵循 checks-effects-interactions
    r"不存在.{0,6}(漏洞|风险|重入)",
    r"已(?:经)?修复",
    r"没有(?:发现)?(?:漏洞|问题)",
]

_NEGATION_RE = re.compile("|".join(_NEGATION_PATTERNS), re.I)


def _tokens(s) -> set:
    return {w for w in re.findall(r"[a-z]+", str(s or "").lower()) if len(w) > 2}


def has_negation(text: str) -> bool:
    """判断模型输出是否带有“这里是安全的/已缓解”的否定语境。"""
    return bool(_NEGATION_RE.search(str(text or "")))


def _norm_type(t, evidence: str = "") -> str:
    """归一化漏洞类型。

    1) 若上下文含否定/缓解语义，直接判为 "none"（不是漏洞报告）；
    2) 用**词边界**匹配别名，避免子串误命中；
    3) 未命中任何别名的，原样返回小写形式（后续按"其他类型"参与比对）。
    """
    if not t:
        return "none"
    if evidence and has_negation(evidence):
        return "none"

    x = str(t).lower().strip()
    if has_negation(x):
        return "none"
    for std, aliases in _TYPE_ALIASES.items():
        if x == std:
            return std
        for a in aliases:
            # 词边界匹配：reentrant 不会命中 non-reentrant（后者已被否定检测拦截）
            if re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", x):
                return std
    return re.sub(r"\s+", "_", x)


def _dedup_findings(findings: list) -> list:
    """对 findings 去重：同一 (类型, 函数, 行) 只保留一条，避免重复计数。"""
    seen, out = set(), []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        key = (
            _norm_type(f.get("vuln_type", ""), f.get("evidence", "")),
            str(f.get("function", "")).strip().lower(),
            str(f.get("line", "")).strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ---------------------------------------------------------------------------
# v1：函数级判分（保留向后兼容）
# ---------------------------------------------------------------------------

def score_report(gt_issues, findings) -> dict:
    """对单样本判分（v1）。

    gt_issues: ground truth，每项 {vuln_type, location:{function:...}} 或 {vuln_type, function:...}
    findings:  模型报告，每项 {vuln_type, function, ...}
    命中 = vuln_type 归一化相同 且 function token 有交集（任一方 function 为空则只按类型判）。
    """
    gt_issues = gt_issues or []
    findings = _dedup_findings(findings)

    used = [False] * len(gt_issues)
    tp = 0
    for f in findings:
        ft = _norm_type(f.get("vuln_type", ""), f.get("evidence", ""))
        if ft == "none":
            continue  # 否定语境不算报告
        ff = _tokens(f.get("function", ""))
        for i, g in enumerate(gt_issues):
            if used[i]:
                continue
            loc = g.get("location", {}) if isinstance(g.get("location"), dict) else {}
            gt_fn = loc.get("function") or g.get("function", "")
            gf = _tokens(gt_fn)
            if ft == _norm_type(g.get("vuln_type", "")) and (not gf or not ff or bool(ff & gf)):
                used[i] = True
                tp += 1
                break

    fp = len(findings) - tp
    fn = len(gt_issues) - tp
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
    }


# ---------------------------------------------------------------------------
# v2：类型 + 定位 IoU + severity 加权
# ---------------------------------------------------------------------------

_SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.3, "": 0.5, "none": 0.5}

# 三维权重：类型 0.5 / 定位 0.3 / 严重级 0.2
_W_TYPE, _W_LOC, _W_SEV = 0.5, 0.3, 0.2
# 质量分达到该阈值才算一个 TP
_TP_THRESHOLD = 0.7


def _sev_weight(sev) -> float:
    return _SEVERITY_WEIGHT.get(str(sev or "").lower().strip(), 0.5)


def _span_of(x) -> tuple:
    """从 finding / issue 中抽取 (start_line, end_line)；取不到返回 (None, None)。"""
    if not isinstance(x, dict):
        return None, None
    loc = x.get("location") if isinstance(x.get("location"), dict) else {}
    s = loc.get("start_line") or x.get("start_line")
    e = loc.get("end_line") or x.get("end_line")
    if s is None and e is None:
        line = x.get("line")
        if line not in (None, "", 0):
            try:
                s = e = int(line)
            except (TypeError, ValueError):
                return None, None
    if s is None or e is None:
        return None, None
    try:
        return int(s), int(e)
    except (TypeError, ValueError):
        return None, None


def _iou_span(a: tuple, b: tuple) -> float:
    """两个行区间的 IoU。b 通常是模型报的单行（视为长度为 1 的区间）。"""
    if a is None or b is None:
        return 0.0
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    inter = max(0, hi - lo + 1)
    union = (a[1] - a[0] + 1) + (b[1] - b[0] + 1) - inter
    return inter / union if union > 0 else 0.0


def _loc_score(g: dict, f: dict, tolerance: int = 15) -> float:
    """定位分 ∈ [0,1]。

    **原则：判分严格度不能超过 ground truth 的标注粒度。**
    我们的 ground truth 是"函数级"的（location 是整个 withdraw 函数的行区间），
    因此模型报出该函数区间内的任意行，都应视为定位正确；不能再苛求行号精确。
    （行号精度若需单独衡量，应另设指标，而不是让它主导 F1。）

    - pred 为点、落在 gt 区间内  → 1.0
    - pred 为点、落在 gt 区间外  → 按距离线性衰减（tolerance 行外归零）
    - 双方皆为区间               → 区间 IoU
    - 无行信息                   → 退化到函数名 token 交集；都没有则 0.5 中性
    """
    gs, ge = _span_of(g)
    fs, fe = _span_of(f)

    if gs is not None and fs is not None:
        if fs == fe and gs != ge:
            # 模型报一个行号，gt 是一个区间
            if gs <= fs <= ge:
                return 1.0
            dist = min(abs(fs - gs), abs(fs - ge))
            return max(0.0, 1.0 - dist / float(tolerance))
        if gs == ge and fs != fe:
            # gt 是单行，模型报区间
            return 1.0 if fs <= gs <= fe else 0.0
        return _iou_span((gs, ge), (fs, fe))

    gt_loc = g.get("location") if isinstance(g.get("location"), dict) else {}
    gt_fn = gt_loc.get("function") or g.get("function", "")
    gf, ff = _tokens(gt_fn), _tokens(f.get("function", ""))
    if gf and ff:
        return 1.0 if (gf & ff) else 0.0
    # 双方都无定位信息：不给定位分也不惩罚，按 0.5 中性处理
    return 0.5


def score_report_v2(gt_issues, findings, tp_threshold: float = _TP_THRESHOLD) -> dict:
    """对单样本做三维打分（v2）。

    每个 (gt, finding) 匹配对产生一个质量分：
        quality = 0.5*类型相符 + 0.3*定位 IoU + 0.2*严重级相符
    quality >= tp_threshold 计为一个 TP；否则该 finding 计为 FP。

    recall / precision 按 severity 权重加权：
        漏掉一个 critical 比漏掉一个 low 代价大得多。
    """
    gt_issues = gt_issues or []
    findings = _dedup_findings(findings)

    # ---- chaff 题（ground truth 为空）：没有雷，"什么都不报"才是正确答案 ----
    # 必须单独处理。否则下面 w_gt_total 会因空列表退化成 1.0，
    # 而 w_hit = 0，recall 被算成 0/1 = 0 —— 于是正确的空报告反而得 0 分，
    # chaff 题完全失效（连"乱报"和"不报"都区分不出来，两者都是 0）。
    # v1 有这个分支，v2 之前漏了。由 run_dummy_check.py 实测发现。
    if not gt_issues:
        correct = not findings
        return {
            "tp": 0,
            "fp": len(findings),
            "fn": 0,
            "n_gt": 0,
            "n_pred": len(findings),
            "recall": 1.0,
            "precision": 1.0 if correct else 0.0,
            "f1": 1.0 if correct else 0.0,
            "mean_quality": 0.0,
            "details": [],
            "is_decoy": True,
        }

    n_gt, n_pred = len(gt_issues), len(findings)
    pairs = []
    for gi, g in enumerate(gt_issues):
        for fi, f in enumerate(findings):
            ft = _norm_type(f.get("vuln_type", ""), f.get("evidence", ""))
            gt_type = _norm_type(g.get("vuln_type", ""))
            if ft == "none" or gt_type == "none":
                continue
            type_ok = 1.0 if ft == gt_type else 0.0
            loc = _loc_score(g, f)
            sev_ok = 1.0 if str(f.get("severity", "")).lower().strip() == \
                str(g.get("severity", "")).lower().strip() else 0.0
            q = _W_TYPE * type_ok + _W_LOC * loc + _W_SEV * sev_ok
            pairs.append((q, gi, fi))

    # 贪心按质量分从高到低配对，每个 gt / finding 只用一次
    pairs.sort(key=lambda x: -x[0])
    used_g, used_f = set(), set()
    matches = []
    for q, gi, fi in pairs:
        if gi in used_g or fi in used_f:
            continue
        used_g.add(gi)
        used_f.add(fi)
        matches.append((q, gi, fi))

    tp = sum(1 for q, _, _ in matches if q >= tp_threshold)

    # ---- severity 加权 ----
    # 注意：precision 的分母**不能**直接用"所有 finding 的 severity 权重之和"。
    # 否则当模型把严重级报低（如 critical 报成 low），分母被压小，precision 会 > 1。
    # 正确做法：命中部分按 ground truth 的权重计入分子，误报部分才用预测方权重。
    w_gt_total = sum(_sev_weight(g.get("severity")) for g in gt_issues) or 1.0
    w_hit = sum(
        _sev_weight(gt_issues[gi].get("severity")) * q
        for q, gi, _ in matches if q >= tp_threshold
    )
    # 未达阈值的匹配：按质量分部分计入，避免"报了但定位差"被完全抹掉
    w_half = 0.5 * sum(
        _sev_weight(gt_issues[gi].get("severity")) * q
        for q, gi, _ in matches if q < tp_threshold
    )
    matched_f = {fi for _, _, fi in matches}
    # 纯误报：完全没匹配上的 finding
    w_fp = sum(_sev_weight(f.get("severity")) for fi, f in enumerate(findings)
               if fi not in matched_f)
    # 部分误报：匹配上了但质量不足，缺口部分视为误报
    w_fp_partial = 0.5 * sum(
        _sev_weight(findings[fi].get("severity")) * (1.0 - q)
        for q, _, fi in matches if q < tp_threshold
    )

    fp = n_pred - tp
    fn = n_gt - tp
    recall = min(1.0, (w_hit + w_half) / w_gt_total)
    denom = w_hit + w_half + w_fp + w_fp_partial
    precision = min(1.0, (w_hit + w_half) / denom) if denom > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n_gt": n_gt,
        "n_pred": n_pred,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "mean_quality": round(sum(q for q, _, _ in matches) / len(matches), 4) if matches else 0.0,
        "details": [
            {"gt_index": gi, "finding_index": fi, "quality": round(q, 4), "is_tp": q >= tp_threshold}
            for q, gi, fi in matches
        ],
    }
