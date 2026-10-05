"""Level 3 审计 Agent：多文件仓库端到端审计。

给模型看注入版合约源码（不告诉它有几个雷、哪些是chaff），
要求输出结构化审计报告：findings 数组，每个 finding 含
vuln_type / contract / function / line / severity / poc 思路。
"""

from __future__ import annotations

import json
import re

from ..llm.client import LLMClient

_PROMPT = """你是资深 Solidity 安全审计专家。给定一个智能合约项目（含主合约和它继承的库），
请做一次完整的端到端安全审计。

要求：
1. 通读所有文件，找出所有安全漏洞。
2. 不要假设漏洞数量——可能 0 个、1 个或多个。
3. 区分真漏洞和chaff（有些代码看起来危险但实际安全，不要报）。
4. 对每个发现的漏洞，给出：
   - vuln_type: reentrancy / access_control / unchecked_call / tx_origin / integer_error / delegatecall / other
   - contract: 合约名
   - function: 出问题的函数名
   - line: 大致行号
   - severity: critical / high / medium / low
   - evidence: 一句话依据
   - poc: 完整的 Foundry 测试代码（.t.sol 文件内容），能编译并跑通证明漏洞存在。
          必须包含：import forge/Test.sol、import 被测合约、contract Test { ... }、
          一个 test_xxx() 函数里用 vm.prank / vm.deal 等 cheatcode 复现攻击，
          最后用 assert 断言攻击成功（如余额变化）。

严格只输出一个 JSON 对象，不要 markdown 代码块、不要任何解释文字：
{"findings":[{...}]}

如果没有发现漏洞，输出 {"findings": []}。
"""


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"findings": []}
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict) and "findings" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return {"findings": []}


class Level3AuditAgent:
    def __init__(self, client: LLMClient):
        self.client = client

    def audit_repo_raw(self, files: dict[str, str]) -> str:
        """返回模型原始输出（不解析 JSON，交给 gate 处理）。"""
        code_block = "\n\n".join(
            f"// ===== FILE: {name} =====\n{src}" for name, src in files.items()
        )
        messages = [
            {"role": "system", "content": _PROMPT},
            {
                "role": "user",
                "content": (
                    "下面是一个智能合约项目的全部源码，请做完整审计并只输出 findings JSON。\n\n"
                    f"```solidity\n{code_block}\n```"
                ),
            },
        ]
        return self.client.chat(messages, max_tokens=4096)

    def audit_repo(self, files: dict[str, str]) -> dict:
        """files: {文件名: 源码}"""
        raw = self.audit_repo_raw(files)
        report = _extract_json(raw)
        findings = report.get("findings", [])
        if not isinstance(findings, list):
            findings = []
        return {"findings": findings, "raw": raw}
