"""ReportScorer：把审计报告对 ground truth 判 recall / precision / F1。

MVP 以“漏洞类型集合”匹配；真实实现还需位置/证据匹配。
关键：precision 与 recall 同时计分，误报（FP）被惩罚，
从而防止“把所有问题类型全报一遍”刷高分。
"""

from __future__ import annotations

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
