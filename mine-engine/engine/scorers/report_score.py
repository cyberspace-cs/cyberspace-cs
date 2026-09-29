"""ReportScorer：把审计报告对 ground truth 判 recall / precision / F1。

关键：precision 与 recall 同时计分，误报（FP）被惩罚，
从而防止“把所有问题全报一遍”刷高分。
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
# 函数级判分：vuln_type 归一化 + function token 交集
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


def _norm_type(t) -> str:
    if not t:
        return ""
    x = str(t).lower().strip()
    for std, aliases in _TYPE_ALIASES.items():
        if x == std or any(a in x for a in aliases):
            return std
    return x


def _tokens(s) -> set:
    return {w for w in re.findall(r"[a-z]+", str(s or "").lower()) if len(w) > 2}


def score_report(gt_issues, findings) -> dict:
    """对单样本判分。

    gt_issues: ground truth，每项 {vuln_type, location:{function:...}} 或 {vuln_type, function:...}
    findings:  模型报告，每项 {vuln_type, function, ...}
    命中 = vuln_type 归一化相同 且 function token 有交集（任一方 function 为空则只按类型判）。
    """
    gt_issues = gt_issues or []
    findings = findings or []

    used = [False] * len(gt_issues)
    tp = 0
    for f in findings:
        ft = _norm_type(f.get("vuln_type", ""))
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
