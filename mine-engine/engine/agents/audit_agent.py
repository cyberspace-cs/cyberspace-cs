"""审计 Agent：给它 planted 合约源码（不给 clean / PoC / ground truth），让它输出结构化 JSON 报告。

MVP 为单轮：一次性把源码喂给模型，要求只返回 findings JSON。
多轮工具调用（读文件 / grep / forge test）是后续扩展。
"""

from __future__ import annotations

import json
import re

from ..llm.client import LLMClient

SYSTEM_PROMPT = """你是资深 Solidity 安全审计专家。给定一个智能合约文件的源码，找出其中所有安全漏洞。

严格只输出一个 JSON 对象，不要 markdown 代码块、不要任何解释文字，格式：
{"findings":[{"vuln_type":"...","function":"...","line":0,"severity":"critical|high|medium|low","evidence":"一句话依据"}]}

vuln_type 从下面词表里选最接近的一个：
reentrancy, access_control, unchecked_call, tx_origin, integer_error, denial, signature_replay, delegatecall

- function 填出问题所在的函数名（或 modifier 名）。
- line 填你判断的大致行号。
- 如果通读后认为没有漏洞，输出 {"findings": []}。
"""


def _extract_json(text: str) -> dict:
    """容忍模型把 JSON 包在 ```json ... ``` 或前后多余文字里。"""
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


class AuditAgent:
    def __init__(self, client: LLMClient):
        self.client = client

    def audit(self, planted_source: str) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "下面是一个智能合约文件的源码，请审计并只输出 findings JSON。\n\n"
                    f"```solidity\n{planted_source}\n```"
                ),
            },
        ]
        raw = self.client.chat(messages, max_tokens=1024)
        report = _extract_json(raw)
        # 规范化 findings 为 list[dict]
        findings = report.get("findings", [])
        if not isinstance(findings, list):
            findings = []
        return {"findings": findings, "raw": raw}
