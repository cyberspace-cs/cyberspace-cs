"""Level 3 四维评分器：识别 / 定位 / 利用 / 报告。

权重（对标 CPA 综合阶段）：
- 识别 20%：recall，真漏洞找全了吗
- 定位 35%：报的 contract+function 对不对
- 利用 30%：有没有给出 PoC 思路（poc 字段非空=0.5，完整=1.0）
- 报告 15%：severity 对不对 + chaff没误报
"""

from __future__ import annotations

import re

_TYPE_ALIASES = {
    "reentrancy": ["reentrancy", "reentrant", "re-entry", "reentry", "重入"],
    "access_control": [
        "access_control", "access control", "authorization", "unprotected",
        "onlyowner", "ownership", "权限", "访问控制", "missing access",
    ],
    "unchecked_call": ["unchecked_call", "unchecked call", "unhandled return"],
    "tx_origin": ["tx_origin", "tx.origin", "txorigin"],
    "integer_error": ["integer", "overflow", "underflow"],
    "delegatecall": ["delegatecall"],
}

# 地面真值：StakingVaultPlanted 的三个雷 + 三个chaff
GROUND_TRUTH = [
    {
        "vuln_type": "reentrancy",
        "contract": "StakingVaultPlanted",
        "function": "withdraw",
        "severity": "critical",
    },
    {
        "vuln_type": "integer_error",
        "contract": "StakingVaultPlanted",
        "function": "interestOf",
        "severity": "high",
    },
    {
        "vuln_type": "access_control",
        "contract": "StakingVaultPlanted",
        "function": "setInterestRate",
        "severity": "high",
    },
]

# chaff：报了这些就算误报
DECOYS = [
    {"contract": "StakingVaultPlanted", "function": "sweep"},
    {"contract": "StakingVaultPlanted", "function": "emergencyWithdraw"},
    {"contract": "StakingVaultPlanted", "function": "togglePause"},
]


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


def score_level3(findings: list) -> dict:
    """对模型输出的 findings 做四维打分。"""
    findings = findings or []
    used = [False] * len(GROUND_TRUTH)

    tp_recall = 0  # 识别命中数
    tp_loc = 0     # 定位命中数（contract+function 都对）
    tp_sev = 0     # severity 对的数
    exploit_score_sum = 0.0  # 利用分

    for f in findings:
        ft = _norm_type(f.get("vuln_type", ""))
        fc = _tokens(f.get("contract", ""))
        ff = _tokens(f.get("function", ""))
        fsev = str(f.get("severity", "")).lower().strip()
        fpoc = str(f.get("poc", "") or "").strip()

        for i, g in enumerate(GROUND_TRUTH):
            if used[i]:
                continue
            gt_type = g["vuln_type"]
            if ft != gt_type:
                continue

            # 识别命中
            used[i] = True
            tp_recall += 1

            # 定位命中：function token 有交集（contract 宽松匹配）
            gt_fn = _tokens(g["function"])
            gt_ct = _tokens(g["contract"])
            if (not gt_ct or not fc or bool(fc & gt_ct)) and (not gt_fn or not ff or bool(ff & gt_fn)):
                tp_loc += 1

            # severity 命中
            gt_sev = g["severity"]
            if fsev == gt_sev:
                tp_sev += 1

            # 利用：poc 非空给 0.5，长度 > 30 给 1.0
            if fpoc:
                exploit_score_sum += 1.0 if len(fpoc) > 30 else 0.5
            break

    # chaff误报数
    fp_decoy = 0
    for f in findings:
        fc = _tokens(f.get("contract", ""))
        ff = _tokens(f.get("function", ""))
        for d in DECOYS:
            dc = _tokens(d["contract"])
            df = _tokens(d["function"])
            if bool(fc & dc) and bool(ff & df):
                fp_decoy += 1

    # 非chaff 的误报（报了不存在的雷）
    tp_total = tp_recall
    fp_random = max(0, len(findings) - tp_total - fp_decoy)

    n_gt = len(GROUND_TRUTH)

    # 识别分：recall
    recall = tp_recall / n_gt if n_gt else 1.0

    # 定位分：定位命中 / 识别命中（识别到的雷里，有多少定位准了）
    loc_score = tp_loc / tp_recall if tp_recall else 0.0

    # 利用分：poc 平均分 / n_gt
    exploit_score = exploit_score_sum / n_gt if n_gt else 1.0

    # 报告分：severity 命中 / 识别命中 * 0.5 + chaff没误报 * 0.5
    sev_score = tp_sev / tp_recall if tp_recall else 0.0
    decoy_score = 1.0 if fp_decoy == 0 else max(0.0, 1.0 - fp_decoy * 0.5)
    report_score = sev_score * 0.5 + decoy_score * 0.5

    # 加权总分
    total = (
        recall * 0.20
        + loc_score * 0.35
        + exploit_score * 0.30
        + report_score * 0.15
    )

    return {
        "tp_recall": tp_recall,
        "tp_loc": tp_loc,
        "tp_sev": tp_sev,
        "fp_decoy": fp_decoy,
        "fp_random": fp_random,
        "recall": round(recall, 3),
        "loc_score": round(loc_score, 3),
        "exploit_score": round(exploit_score, 3),
        "report_score": round(report_score, 3),
        "total": round(total, 3),
        "n_findings": len(findings),
    }
