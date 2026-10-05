"""IssueOperator：重入注入算子。

在健康 Vault 源码上做一次确定性、最小化的程序变换：
  1) 合约名 Vault -> VaultPlanted；
  2) 在 withdraw 中，把“余额清零（Effects）”这一行，从外部 call 之前
     移动到外部 call / require 之后 —— 即制造经典重入漏洞（SWC-107）。
其余代码一字不动，从而保证“雷确实是这次埋进去的”。
"""

from __future__ import annotations

import re

from ..core.pipeline import IssueOperator
from ..core.schema import Issue, Location

OLD_CONTRACT = "Vault"
NEW_CONTRACT = "VaultPlanted"


def _function_span(lines, fname):
    """返回函数 (起始行, 结束行) 的 0-based 索引，用花括号配平。"""
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"\s*function\s+{fname}\b", line):
            start = i
            break
    if start is None:
        return None
    depth = 0
    begun = False
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if "{" in lines[i]:
            begun = True
        if begun and depth == 0:
            return start, i
    return None


def inject_reentrancy(clean_source: str):
    """对健康 Vault 源码注入重入漏洞，返回 (planted_source, (起,止 1-based))。"""
    lines = clean_source.splitlines()

    # 1) 重命名合约
    renamed = False
    for i, line in enumerate(lines):
        if re.match(rf"\s*contract\s+{OLD_CONTRACT}\b", line):
            lines[i] = re.sub(
                rf"\bcontract\s+{OLD_CONTRACT}\b",
                f"contract {NEW_CONTRACT}",
                line,
            )
            renamed = True
            break
    if not renamed:
        raise RuntimeError("未找到 contract Vault 声明")

    # 2) 定位 withdraw 与三条锚点行
    span = _function_span(lines, "withdraw")
    if span is None:
        raise RuntimeError("未找到 withdraw 函数")
    s, e = span
    effect_idx = call_idx = require_idx = None
    for i in range(s, e + 1):
        text = lines[i].strip()
        if text == "balances[msg.sender] = 0;":
            effect_idx = i
        elif text.startswith("(bool ok"):
            call_idx = i
        elif text.startswith("require(ok"):
            require_idx = i
    if None in (effect_idx, call_idx, require_idx):
        raise RuntimeError(
            f"锚点缺失: effect={effect_idx}, call={call_idx}, require={require_idx}"
        )
    if not (effect_idx < call_idx < require_idx):
        raise RuntimeError("健康布局异常（可能已经被埋过雷）")

    # 3) 把 Effects 行移动到 require 之后
    effect_line = lines[effect_idx]
    del lines[effect_idx]
    require_idx -= 1  # 删除了前面一行，索引整体前移
    lines.insert(require_idx + 1, effect_line)

    planted = "\n".join(lines)
    if not planted.endswith("\n"):
        planted += "\n"

    planted_span = _function_span(lines, "withdraw")
    ps, pe = planted_span
    return planted, (ps + 1, pe + 1)  # 转 1-based


class ReentrancyInjector(IssueOperator):
    name = "reentrancy-injector"

    def __init__(self, swc: str = "SWC-107", seed: int = 42, start_index: int = 0, **config):
        super().__init__(**config)
        self.swc = swc
        self.seed = seed
        self.start_index = start_index

    def run(self, records):
        out = []
        for n, rec in enumerate(records):
            planted, (start_line, end_line) = inject_reentrancy(rec["clean_source"])
            sample_id = f"sample-{self.start_index + n + 1:04d}"
            issue = Issue(
                issue_id=f"{sample_id}-reentrancy",
                sample_id=sample_id,
                vuln_type="reentrancy",
                swc=self.swc,
                severity="critical",
                location=Location(
                    file="planted/VaultPlanted.sol",
                    function="withdraw",
                    start_line=start_line,
                    end_line=end_line,
                ),
                difficulty=2,
                poc="VaultReentrancyPoC.t.sol::test_Reentrancy_Planted_AttackSucceeds",
                discovery_hint="对照 CEI：检查 withdraw 中外部 call 与余额清零的先后顺序",
                operator="ReentrancyInjector",
                seed=self.seed,
            )
            out.append(
                {
                    **rec,
                    "sample_id": sample_id,
                    "planted_contract_name": NEW_CONTRACT,
                    "planted_source": planted,
                    "issues": [issue.to_dict()],
                }
            )
        return out
