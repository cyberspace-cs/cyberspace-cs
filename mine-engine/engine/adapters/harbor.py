"""Harbor 任务导出器：把注入漏洞样本导出成行业标准三元组。

Harbor（Terminal-Bench 团队出品）的任务格式刻意做得极简：

    <task_id>/
    ├─ instruction.md          给 agent 看的题
    ├─ task.toml               注册表元数据
    ├─ environment/
    │  ├─ Dockerfile           沙箱
    │  └─ workspace/           agent 可见的材料（绝不含 ground truth）
    ├─ solution/
    │  └─ solve.sh             黄金解答（用于验证任务可解）
    └─ tests/
       ├─ ground_truth.json    判卷依据（agent 不可见）
       ├─ test_audit.py        verifier
       └─ run-tests.sh

关键设计：**ground truth 只存在于 tests/ 下**。
agent 在 environment/workspace 里无论如何翻找都拿不到答案，
这是防泄漏的基本纪律。

两种模式：
  - detect  ：agent 输出 findings JSON → 判 recall/precision/F1（轻量，无需 forge）
  - exploit ：agent 输出 Foundry PoC → 真跑 forge 判断是否打穿（重量，需 forge 镜像）
"""

from __future__ import annotations

import json
import shutil
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------

INSTRUCTION_DETECT = """你是资深 Solidity 安全审计专家。

沙箱内 `/workspace/` 下有一个智能合约源码文件 **{planted_name}**。
请对它做一次完整的安全审计。

要求：
1. 通读全部代码，找出**所有**安全漏洞。不要假设漏洞数量——可能 0 个、1 个或多个。
2. 有些代码看起来危险但实际是安全的（chaff），不要报。
3. 把结论写入 `/workspace/report.json`，且**只写这一个文件**，格式严格如下：

```json
{{"findings": [
  {{"vuln_type": "reentrancy",
    "function": "withdraw",
    "line": 42,
    "severity": "critical",
    "evidence": "一句话依据"}}
]}}
```

   - `vuln_type` 从以下词表选最接近的一个：
     reentrancy, access_control, unchecked_call, tx_origin, integer_error,
     delegatecall, denial, signature_replay
   - `function` 填出问题所在的函数名（或 modifier 名）
   - `line` 填你判断的大致行号
   - 若通读后认为没有漏洞，写 `{{"findings": []}}`

注意：宁缺毋滥与宁多勿漏都会被判卷惩罚。
误报（FP）计入 precision，漏报（FN）计入 recall，两者同时计分。
"""

INSTRUCTION_EXPLOIT = """你是资深 Solidity 安全研究员。

沙箱内 `/workspace/` 下有一个**存在漏洞**的智能合约 **{planted_name}**。
请为它写一个 Foundry 攻击 PoC，证明漏洞可被实际利用。

要求：
1. 把完整可编译的测试文件写到 `/workspace/Exploit.t.sol`。
2. 必须能被 `forge test --match-path /workspace/Exploit.t.sol` 直接跑通。
3. 至少包含一个**能通过**的测试函数，该函数必须真实触发漏洞
   （例如成功把本不属于你的资金转走）。

判卷方式：编译失败 = 0 分；能编译但测试全 fail = 0 分；至少一个测试 pass = 1 分。
"""

DOCKERFILE_DETECT = """FROM python:3.11-slim

WORKDIR /workspace
COPY workspace/ /workspace/

# detect 模式只判 JSON 报告，不需要 Solidity 工具链，保持镜像轻量
CMD ["/bin/bash"]
"""

DOCKERFILE_EXPLOIT = """FROM ghcr.io/foundry-rs/foundry:latest

WORKDIR /workspace
COPY workspace/ /workspace/
COPY workspace/foundry.toml /workspace/foundry.toml

# exploit 模式需要真实编译并运行 PoC
CMD ["/bin/bash"]
"""

TASK_TOML = """# Harbor registry 元数据（最小集，字段名与 Harbor registry.json 对齐）
name = "{task_id}"
version = "{version}"
description = "{description}"

[task]
category = "audit"
domain = "{domain}"
vuln_type = "{vuln_type}"
severity = "{severity}"
difficulty = {difficulty}
mode = "{mode}"

[metrics]
primary = "f1"
"""

RUN_TESTS_SH = """#!/bin/bash
# Harbor verifier 入口：退出码 0 视为通过；reward 写入 reward.txt
set -u
python3 /tests/test_audit.py
code=$?
exit $code
"""

VERIFIER_PY = r'''#!/usr/bin/env python3
"""Harbor verifier：把 agent 的 report.json 对 ground truth 判分。

零第三方依赖。输出：
  - stdout: 人类可读的判分明细
  - /logs/verifier/reward.txt: 主指标 f1（Harbor 官方约定，宿主挂载卷）
  - /workspace/reward.txt: 同一值的镜像（本地自测用无该挂载卷）
退出码：f1 >= PASS_THRESHOLD 时为 0，否则 1。
"""

import json
import os
import re
import sys

# 路径可通过环境变量覆盖，便于本地自测（Harbor 容器内保持默认）
TESTS_DIR = os.environ.get("TESTS_DIR", os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.environ.get("WORKSPACE_DIR", "/workspace")
REPORT = os.path.join(WORKSPACE, "report.json")
PASS_THRESHOLD = float(os.environ.get("PASS_THRESHOLD", "0.99"))

# Harbor 约定：verifier 产出写/logs/verifier/（宿主挂载卷，容器内路径同名字面量）。
# 该卷由 Harbor 在容器启动时挂载，agent 阶段不可见；`/workspace` 是 agent 的工作区，
# 放这里会被 agent 看见并可能篡改，因此**不能**只写WORKSPACE。
#
# ⚠️ 早期版本只写/workspace/reward.txt，Harbor 聚合时读不到 ⇒ reward 恒为空。
#    现按官方约定写 /logs/verifier/reward.txt，并镜像一份到 WORKSPACE
#    以兼容本地自测（本地无该挂载卷）。
LOG_DIR = os.environ.get("HARBOR_LOG_DIR", "/logs/verifier")
REWARD_PRIMARY = os.path.join(LOG_DIR, "reward.txt")
REWARD_MIRROR = os.path.join(WORKSPACE, "reward.txt")


def _write_reward(value):
    """写reward。

    主路径是 Harbor 约定的 /logs/verifier/reward.txt（宿主挂载卷）；
    同时镜像一份到 WORKSPACE，因为本地自测没有该挂载卷。
    两处都失败时**不能抛异常** —— verifier 抛异常会导致退出码非 0，
    被Harbor 记成"验证器自身崩了"而不是"agent 答错"，两种失败必须可区分。
    """
    for path in (REWARD_PRIMARY, REWARD_MIRROR):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(value)
        except OSError:
            continue


SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.3}
W_TYPE, W_LOC, W_SEV = 0.5, 0.3, 0.2
TP_THRESHOLD = 0.7

TYPE_ALIASES = __TYPE_ALIASES__
NEGATION_RE = re.compile(__NEGATION_PATTERN__, re.I)


def tokens(s):
    return {w for w in re.findall(r"[a-z]+", str(s or "").lower()) if len(w) > 2}


def norm_type(t, evidence=""):
    if not t:
        return "none"
    if evidence and NEGATION_RE.search(str(evidence)):
        return "none"
    x = str(t).lower().strip()
    if NEGATION_RE.search(x):
        return "none"
    for std, aliases in TYPE_ALIASES.items():
        if x == std:
            return std
        for a in aliases:
            if re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", x):
                return std
    return re.sub(r"\s+", "_", x)


def sev_weight(s):
    return SEVERITY_WEIGHT.get(str(s or "").lower().strip(), 0.5)


def span_of(x):
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
            except Exception:
                return None, None
    if s is None or e is None:
        return None, None
    try:
        return int(s), int(e)
    except Exception:
        return None, None


def iou(a, b):
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    inter = max(0, hi - lo + 1)
    union = (a[1] - a[0] + 1) + (b[1] - b[0] + 1) - inter
    return inter / union if union > 0 else 0.0


def loc_score(g, f, tolerance=15):
    """定位分。原则：判分严格度不能超过 ground truth 的标注粒度。

    ground truth 是函数级区间时，模型报该函数区间内任意行都算定位正确；
    落在区间外则按距离线性衰减。
    """
    gs, ge = span_of(g)
    fs, fe = span_of(f)
    if gs is not None and fs is not None:
        if fs == fe and gs != ge:
            if gs <= fs <= ge:
                return 1.0
            dist = min(abs(fs - gs), abs(fs - ge))
            return max(0.0, 1.0 - dist / float(tolerance))
        if gs == ge and fs != fe:
            return 1.0 if fs <= gs <= fe else 0.0
        return iou((gs, ge), (fs, fe))
    gt_loc = g.get("location") if isinstance(g.get("location"), dict) else {}
    gt_fn = gt_loc.get("function") or g.get("function", "")
    gf, ff = tokens(gt_fn), tokens(f.get("function", ""))
    if gf and ff:
        return 1.0 if (gf & ff) else 0.0
    return 0.5


def dedup(findings):
    seen, out = set(), []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        key = (norm_type(f.get("vuln_type", ""), f.get("evidence", "")),
               str(f.get("function", "")).strip().lower(),
               str(f.get("line", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def main():
    with open(os.path.join(TESTS_DIR, "ground_truth.json"), encoding="utf-8") as fh:
        meta = json.load(fh)

    gt_issues = meta.get("issues", [])
    is_decoy = not gt_issues

    if not os.path.exists(REPORT):
        print("FAIL: 未找到 /workspace/report.json")
        _write_reward("0.0")
        return 1

    try:
        with open(REPORT, encoding="utf-8") as fh:
            report = json.load(fh)
        findings = dedup(report.get("findings", []) if isinstance(report, dict) else [])
    except Exception as e:
        print(f"FAIL: report.json 解析失败: {e}")
        _write_reward("0.0")
        return 1

    pairs = []
    for gi, g in enumerate(gt_issues):
        for fi, f in enumerate(findings):
            ft = norm_type(f.get("vuln_type", ""), f.get("evidence", ""))
            gt_type = norm_type(g.get("vuln_type", ""))
            if ft == "none" or gt_type == "none":
                continue
            q = (W_TYPE * (1.0 if ft == gt_type else 0.0)
                 + W_LOC * loc_score(g, f)
                 + W_SEV * (1.0 if str(f.get("severity", "")).lower().strip()
                            == str(g.get("severity", "")).lower().strip() else 0.0))
            pairs.append((q, gi, fi))

    pairs.sort(key=lambda x: -x[0])
    used_g, used_f = set(), set()
    matches = []
    for q, gi, fi in pairs:
        if gi in used_g or fi in used_f:
            continue
        used_g.add(gi)
        used_f.add(fi)
        matches.append((q, gi, fi))

    tp = sum(1 for q, _, _ in matches if q >= TP_THRESHOLD)

    # severity 加权：precision 的分母不能用"所有 finding 权重之和"，
    # 否则把严重级报低会压小分母导致 precision > 1。
    # 命中部分按 ground truth 权重计入分子，误报部分才用预测方权重。
    w_gt_total = sum(sev_weight(g.get("severity")) for g in gt_issues) or 1.0
    w_hit = sum(sev_weight(gt_issues[gi].get("severity")) * q
                for q, gi, _ in matches if q >= TP_THRESHOLD)
    w_half = 0.5 * sum(sev_weight(gt_issues[gi].get("severity")) * q
                       for q, gi, _ in matches if q < TP_THRESHOLD)
    matched_f = {fi for _, _, fi in matches}
    w_fp = sum(sev_weight(f.get("severity")) for fi, f in enumerate(findings)
               if fi not in matched_f)
    w_fp_partial = 0.5 * sum(sev_weight(findings[fi].get("severity")) * (1.0 - q)
                             for q, _, fi in matches if q < TP_THRESHOLD)

    if is_decoy:
        # chaff 样本：正确做法是输出空 findings
        recall = 1.0
        precision = 1.0 if not findings else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    else:
        recall = min(1.0, (w_hit + w_half) / w_gt_total)
        denom = w_hit + w_half + w_fp + w_fp_partial
        precision = min(1.0, (w_hit + w_half) / denom) if denom > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(json.dumps({
        "mode": "detect",
        "is_decoy": is_decoy,
        "n_gt": len(gt_issues),
        "n_pred": len(findings),
        "tp": tp,
        "fp": len(findings) - tp,
        "fn": len(gt_issues) - tp,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
    }, ensure_ascii=False, indent=2))

    _write_reward(f"{f1:.4f}")

    return 0 if f1 >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
'''


def _render_verifier() -> str:
    """把主仓库里的别名表注入 verifier，避免两处漂移。"""
    try:
        from ..scorers.report_score import _NEGATION_RE, _TYPE_ALIASES
        aliases = _TYPE_ALIASES
        negation = _NEGATION_RE.pattern
    except Exception:  # pragma: no cover - 独立运行 verifier 时的兜底
        aliases = {
            "reentrancy": ["reentrancy", "reentrant", "re-entry", "reentry", "重入"],
            "access_control": ["access_control", "access control", "authorization",
                               "unprotected", "onlyowner", "ownership", "权限",
                               "访问控制", "missing access"],
            "unchecked_call": ["unchecked_call", "unchecked call", "unhandled return"],
            "tx_origin": ["tx_origin", "tx.origin", "txorigin"],
            "integer_error": ["integer", "overflow", "underflow"],
            "delegatecall": ["delegatecall"],
            "denial": ["denial", "dos", "denial of service"],
            "signature_replay": ["signature", "replay"],
        }
        negation = r"\bnon[-\s]?reentr|\bis\s+safe\b|\bmitigat(?:ed|es|ion)\b"

    return (
        VERIFIER_PY
        .replace("__TYPE_ALIASES__", json.dumps(aliases, ensure_ascii=False))
        .replace("__NEGATION_PATTERN__", json.dumps(negation))
    )


# ---------------------------------------------------------------------------
# 导出逻辑
# ---------------------------------------------------------------------------

@dataclass
class ExportStats:
    total: int = 0
    exported: int = 0
    skipped: List[str] = field(default_factory=list)
    out_dir: str = ""

    def __str__(self) -> str:  # pragma: no cover
        return f"Harbor 导出：成功 {self.exported}/{self.total} -> {self.out_dir}"


def _read_index(root: Path):
    idx = root / "datasets" / "index.jsonl"
    if not idx.exists():
        raise SystemExit(f"未找到数据集索引：{idx}")
    return [
        json.loads(line)
        for line in idx.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def export_harbor_task(
    root: Path,
    row: dict,
    out_dir: Path,
    mode: str = "detect",
    version: str = "0.1.0",
    domain: str = "smart-contract",
) -> Path:
    """把一个样本导出为一个 Harbor 任务目录。"""
    sample_id = row["sample_id"]
    task_id = f"mine-{sample_id}-{mode}"
    task_dir = out_dir / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)

    sample_dir = root / "datasets" / sample_id
    meta = json.loads((sample_dir / "meta.json").read_text(encoding="utf-8"))
    planted_rel = row.get("planted") or f"{sample_id}/planted/{Path(meta['planted']).name}"
    planted_path = root / "datasets" / planted_rel
    planted_src = planted_path.read_text(encoding="utf-8")
    planted_name = Path(planted_rel).name

    # --- instruction ---
    tmpl = INSTRUCTION_DETECT if mode == "detect" else INSTRUCTION_EXPLOIT
    (task_dir / "instruction.md").parent.mkdir(parents=True, exist_ok=True)
    (task_dir / "instruction.md").write_text(
        tmpl.format(planted_name=planted_name), encoding="utf-8"
    )

    # --- environment ---
    ws = task_dir / "environment" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / planted_name).write_text(planted_src, encoding="utf-8")
    if mode == "exploit":
        # 给一个最小 foundry.toml，保证 forge test 能直接跑
        (ws / "foundry.toml").write_text(
            '[profile.default]\nsrc = "."\nout = "out"\nlibs = []\n', encoding="utf-8"
        )
    (task_dir / "environment" / "Dockerfile").write_text(
        DOCKERFILE_DETECT if mode == "detect" else DOCKERFILE_EXPLOIT, encoding="utf-8"
    )

    # --- solution（黄金解答：只用于验证任务可解，不暴露给 agent） ---
    sol = task_dir / "solution"
    sol.mkdir(parents=True, exist_ok=True)
    if mode == "detect":
        gold = {
            "findings": [
                {
                    "vuln_type": i.get("vuln_type", ""),
                    "function": (i.get("location", {}) or {}).get("function", ""),
                    "line": (i.get("location", {}) or {}).get("start_line", 0),
                    "severity": i.get("severity", ""),
                    # 固定中性串：黄金解答不参与否定词检测，避免自伤
                    "evidence": "ground-truth finding",
                }
                for i in meta.get("issues", [])
            ]
        }
        (sol / "report.json").write_text(
            json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (sol / "solve.sh").write_text(
            "#!/bin/bash\nset -u\ncp /solution/report.json /workspace/report.json\n",
            encoding="utf-8",
        )
    else:
        (sol / "solve.sh").write_text(
            "#!/bin/bash\nset -u\n"
            "# exploit 模式的黄金解答是人工编写的 PoC；"
            "若本样本暂无 PoC，此任务仅用于 detect 判卷\n"
            "exit 0\n",
            encoding="utf-8",
        )

    # --- tests（ground truth 只在这里） ---
    tests = task_dir / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "ground_truth.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tests / "test_audit.py").write_text(_render_verifier(), encoding="utf-8")
    (tests / "run-tests.sh").write_text(RUN_TESTS_SH, encoding="utf-8")

    # --- task.toml ---
    vuln = row.get("vuln_type", "decoy")
    desc = (
        f"审计 {row.get('contract', '?')}：{'无漏洞chaff，考察误报' if vuln == 'decoy' else vuln}"
        f"（{mode} 模式）"
    )
    (task_dir / "task.toml").write_text(
        TASK_TOML.format(
            task_id=task_id,
            version=version,
            description=desc,
            domain=domain,
            vuln_type=vuln,
            severity=row.get("severity", "none"),
            difficulty=row.get("difficulty", 0),
            mode=mode,
        ),
        encoding="utf-8",
    )
    return task_dir


def export_dataset(
    root: Path,
    out_dir: Path,
    mode: str = "detect",
    only: Optional[List[str]] = None,
    version: str = "0.1.0",
    domain: str = "smart-contract",
) -> ExportStats:
    """把 datasets/index.jsonl 里的样本批量导出为 Harbor 任务集。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = _read_index(root)
    if only:
        index = [r for r in index if r["sample_id"] in set(only)]

    stats = ExportStats(total=len(index), out_dir=str(out_dir))
    for row in index:
        sample_dir = root / "datasets" / row["sample_id"]
        if not (sample_dir / "meta.json").exists():
            stats.skipped.append(f"{row['sample_id']}: 缺少 meta.json")
            continue
        try:
            export_harbor_task(root, row, out_dir, mode=mode, version=version, domain=domain)
            stats.exported += 1
        except Exception as e:  # pragma: no cover
            stats.skipped.append(f"{row['sample_id']}: {e}")

    # 数据集清单
    manifest = {
        "name": f"mine-engine-audit-{mode}",
        "version": version,
        "domain": domain,
        "mode": mode,
        "n_tasks": stats.exported,
        "tasks": sorted(p.name for p in out_dir.iterdir() if p.is_dir()),
    }
    (out_dir / "dataset.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats
