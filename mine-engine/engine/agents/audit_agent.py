"""审计 Agent：给它 planted 合约源码（不给 clean / PoC / ground truth），让它输出结构化 JSON 报告。

Prompt 策略参数化（对齐 DataFlow 的 Prompt 一等公民）：同一模型可换不同审计策略 A/B。
MVP 为单轮：一次性把源码喂给模型，要求只返回 findings JSON。
"""

from __future__ import annotations

import json
import re

from ..llm.client import LLMClient

_BASE_FORMAT = """严格只输出一个 JSON 对象，不要 markdown 代码块、不要任何解释文字，格式：
{"findings":[{"vuln_type":"...","function":"...","line":0,"severity":"critical|high|medium|low","evidence":"一句话依据"}]}

vuln_type 从下面词表里选最接近的一个：
reentrancy, access_control, unchecked_call, tx_origin, integer_error, denial, signature_replay, delegatecall

- function 填出问题所在的函数名（或 modifier 名）。
- line 填你判断的大致行号。
- 如果通读后认为没有漏洞，输出 {"findings": []}。
"""

# 三套审计策略（A/B 实验变量）
PROMPT_STRATEGIES = {
    "standard": (
        "你是资深 Solidity 安全审计专家。给定一个智能合约文件的源码，找出其中所有安全漏洞。\n\n"
        + _BASE_FORMAT
    ),
    "conservative": (
        "你是非常谨慎的 Solidity 审计专家。给定合约源码，只报告你有充分证据确定的漏洞；"
        "证据不足就不要报，宁缺毋滥。\n\n" + _BASE_FORMAT
    ),
    "aggressive": (
        "你是激进的 Solidity 审计专家，倾向于宁多勿漏。给定合约源码，把所有疑似可疑的模式都报出来，"
        "即使不确定也报为 lower severity。\n\n" + _BASE_FORMAT
    ),
}


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
    def __init__(self, client: LLMClient, strategy: str = "standard",
                 max_tokens: int | None = None):
        self.client = client
        if strategy not in PROMPT_STRATEGIES:
            raise KeyError(f"未知 prompt 策略: {strategy}，可选 {list(PROMPT_STRATEGIES)}")
        self.strategy = strategy
        self.system_prompt = PROMPT_STRATEGIES[strategy]
        # None = 用 client 的默认上限（LLM_MAX_TOKENS）。thinking 模型需要更大的预算。
        self.max_tokens = max_tokens

    def audit(self, planted_source: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    "下面是一个智能合约文件的源码，请审计并只输出 findings JSON。\n\n"
                    f"```solidity\n{planted_source}\n```"
                ),
            },
        ]
        # 用 chat_detailed 而非 chat，才能拿到 token 用量与耗时。
        # （chat() 只返回文本，用量会被丢掉 —— 成本就无从计算）
        resp = self.client.chat_detailed(messages, max_tokens=self.max_tokens)
        report = _extract_json(resp.text)
        findings = report.get("findings", [])
        if not isinstance(findings, list):
            findings = []
        # _usage 下划线开头：明确表示这是元信息，不参与判分。
        # truncated=True 时 findings 是空的是**预算问题**，不是"模型认为没漏洞"——
        # 两者外表一样（都是空 findings），必须用元信息区分，否则评测结果会悄悄失真。
        usage = resp.as_dict()
        usage["empty_text"] = resp.empty_text
        return {
            "findings": findings,
            "raw": resp.text,
            "_usage": usage,
        }
