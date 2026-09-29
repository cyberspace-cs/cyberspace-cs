"""TxOriginInjector：tx.origin 授权埋雷算子（SWC-115）。

在健康 Wallet 源码上做确定性变换：
  1) contract 名 Wallet -> WalletPlanted；
  2) 授权判断 `require(msg.sender == owner, "not owner")`
     -> `require(tx.origin == owner, "not owner")`，
     使任何由 owner EOA 发起、经合约中转的调用都被放行。
其余代码一字不动。
"""

from __future__ import annotations

import re

from ..core.pipeline import IssueOperator
from ..core.schema import Issue, Location

OLD_CONTRACT = "Wallet"
NEW_CONTRACT = "WalletPlanted"


def inject_tx_origin(clean_source: str):
    lines = clean_source.splitlines()

    renamed = False
    for i, line in enumerate(lines):
        if re.match(rf"\s*contract\s+{OLD_CONTRACT}\b", line):
            lines[i] = re.sub(rf"\bcontract\s+{OLD_CONTRACT}\b", f"contract {NEW_CONTRACT}", line)
            renamed = True
            break
    if not renamed:
        raise RuntimeError("未找到 contract Wallet 声明")

    changed_line = None
    for i, line in enumerate(lines):
        if re.search(r"require\(\s*msg\.sender\s*==\s*owner\s*,", line):
            lines[i] = re.sub(r"msg\.sender\s*==\s*owner", "tx.origin == owner", line)
            changed_line = i + 1
            break
    if changed_line is None:
        raise RuntimeError("未找到 msg.sender == owner 的授权 require")

    planted = "\n".join(lines)
    if not planted.endswith("\n"):
        planted += "\n"
    return planted, (changed_line, changed_line)


class TxOriginInjector(IssueOperator):
    name = "tx-origin-injector"

    def __init__(self, swc: str = "SWC-115", seed: int = 42, start_index: int = 0, **config):
        super().__init__(**config)
        self.swc = swc
        self.seed = seed
        self.start_index = start_index

    def run(self, records):
        out = []
        for n, rec in enumerate(records):
            planted, (sl, el) = inject_tx_origin(rec["clean_source"])
            sample_id = f"sample-{self.start_index + n + 1:04d}"
            issue = Issue(
                issue_id=f"{sample_id}-tx-origin",
                sample_id=sample_id,
                vuln_type="tx_origin",
                swc=self.swc,
                severity="high",
                location=Location(
                    file="planted/WalletPlanted.sol",
                    function="transferTo",
                    start_line=sl,
                    end_line=el,
                ),
                difficulty=2,
                poc="WalletTxOriginPoC.t.sol::test_TxOrigin_Planted_AttackSucceeds",
                discovery_hint="检查授权判断用的是 msg.sender 还是 tx.origin",
                operator="TxOriginInjector",
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
