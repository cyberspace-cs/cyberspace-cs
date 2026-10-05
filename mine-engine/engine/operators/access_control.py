"""IssueOperator：访问控制缺失注入算子（SWC-105）。

在健康 Ownable 源码上做一次确定性、最小化变换：
  1) 合约名 Ownable -> OwnablePlanted；
  2) 删除 onlyOwner modifier 中的身份校验
     `require(msg.sender == owner, "not owner");`，
     使 modifier 退化为 `{ _; }`，所有“仅 owner”函数任何人可调用。
其余代码一字不动。
"""

from __future__ import annotations

import re

from ..core.pipeline import IssueOperator
from ..core.schema import Issue, Location

OLD_CONTRACT = "Ownable"
NEW_CONTRACT = "OwnablePlanted"


def _named_block_span(lines, kind: str, name: str):
    """定位 `kind name`（如 modifier onlyOwner）块的 0-based (起,止)，花括号配平。"""
    pattern = re.compile(rf"\s*{kind}\s+{name}\b")
    start = None
    for i, line in enumerate(lines):
        if pattern.match(line):
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


def inject_access_control(clean_source: str):
    lines = clean_source.splitlines()

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
        raise RuntimeError("未找到 contract Ownable 声明")

    span = _named_block_span(lines, "modifier", "onlyOwner")
    if span is None:
        raise RuntimeError("未找到 onlyOwner modifier")
    ms, me = span

    require_re = re.compile(
        r'\s*require\(\s*msg\.sender\s*==\s*owner\s*,\s*"not owner"\s*\)\s*;\s*$'
    )
    target = None
    for i in range(ms, me + 1):
        if require_re.match(lines[i]):
            target = i
            break
    if target is None:
        raise RuntimeError("未找到 onlyOwner 中的身份校验 require")

    del lines[target]

    planted = "\n".join(lines)
    if not planted.endswith("\n"):
        planted += "\n"

    planted_span = _named_block_span(lines, "modifier", "onlyOwner")
    ps, pe = planted_span
    return planted, (ps + 1, pe + 1)


class AccessControlInjector(IssueOperator):
    name = "access-control-injector"

    def __init__(self, swc: str = "SWC-105", seed: int = 42, start_index: int = 0, **config):
        super().__init__(**config)
        self.swc = swc
        self.seed = seed
        self.start_index = start_index

    def run(self, records):
        out = []
        for n, rec in enumerate(records):
            planted, (start_line, end_line) = inject_access_control(rec["clean_source"])
            sample_id = f"sample-{self.start_index + n + 1:04d}"
            issue = Issue(
                issue_id=f"{sample_id}-access-control",
                sample_id=sample_id,
                vuln_type="access_control",
                swc=self.swc,
                severity="high",
                location=Location(
                    file="planted/OwnablePlanted.sol",
                    function="modifier onlyOwner",
                    start_line=start_line,
                    end_line=end_line,
                ),
                difficulty=1,
                poc="OwnableAccessControlPoC.t.sol::test_AccessControl_Planted_NonOwnerSucceeds",
                discovery_hint="检查 onlyOwner modifier 是否真的校验了 msg.sender == owner",
                operator="AccessControlInjector",
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
