"""VariationOperator：LLM 语义保持改写（借鉴 DataFlow 的 PromptedGenerator）。

对已注入漏洞的 planted 源码做浅层改写：改局部变量名 / 加注释 / 调整不影响语义的语句，
但**保持合约名、函数签名、漏洞点行为不变**。变体产出后必须再过 Foundry 差分闸门，
编译不过 / 破坏 happy-path / PoC 不再差分的变体会被自动丢弃。

这是解决"确定性算子批量=同一份代码复制"的关键：一道注入漏洞题可自动长出多道语义不同、
漏洞相同的变体，数据集才真正多样化。
"""

from __future__ import annotations

import re

from ..core.pipeline import IssueOperator
from ..llm.client import LLMClient

VARIATION_SYSTEM = """你是 Solidity 代码变体生成器。下面是一个合约。请做"语义保持的改写"：
- 保持合约名、所有函数签名、事件名、pragma 完全不变；
- 保持所有业务逻辑与安全漏洞的位置/行为完全不变；
- 只做浅层变化：改局部变量名（如 amount -> bal）、加简短注释、调整不影响语义的语句顺序、合并简单表达式；
- 不要新增/删除函数，不要改 modifier 名，不要改 require 的条件。
直接输出改写后的完整 .sol 文件，不要任何解释。"""


def _extract_solidity(text: str) -> str:
    m = re.search(r"```solidity\s*(.*?)```", text, re.S)
    return m.group(1).strip() if m else text.strip()


class VariationOperator(IssueOperator):
    name = "variation-operator"

    def __init__(self, client: LLMClient, k: int = 1, **config):
        super().__init__(**config)
        self.client = client
        self.k = k

    def run(self, records):
        out = list(records)
        for rec in records:
            if not rec.get("issues"):  # chaff 不变体
                continue
            for i in range(self.k):
                try:
                    raw = self.client.chat(
                        [
                            {"role": "system", "content": VARIATION_SYSTEM},
                            {"role": "user", "content": f"```solidity\n{rec['planted_source']}\n```"},
                        ],
                        max_tokens=1500,
                    )
                    body = _extract_solidity(raw)
                    out.append(
                        {
                            **rec,
                            "sample_id": f"{rec['sample_id']}-v{i + 1}",
                            "planted_source": body,
                            "variation": True,
                        }
                    )
                except Exception:
                    # 变体生成失败就跳过，不影响主样本
                    continue
        return out

    FIX_SYSTEM = """你是 Solidity 代码修复器。下面是一段合约，以及上一次提交后 Foundry 差分验证的报错。
请只修导致验证失败的问题（编译错误 / 破坏正常功能 / 让漏洞不再可被 PoC 触发），
保持合约名、函数签名、漏洞位置与行为不变。
直接输出修正后的完整 .sol 文件，不要任何解释。"""

    def fix_variant(self, rec: dict, error_log: str, max_tokens: int = 1500) -> "str | None":
        """自我修正循环（行动方案第三步）：把验证失败的错误喂回 LLM，返回修正后源码。

        返回 None 表示修复失败（LLM 不可用 / 解析不出 .sol / 异常）。
        """
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": self.FIX_SYSTEM},
                    {"role": "user", "content": (
                        f"【上一次验证报错】\n{error_log[-3000:]}\n\n"
                        f"【待修复合约】\n```solidity\n{rec['planted_source']}\n```"
                    )},
                ],
                max_tokens=max_tokens,
            )
            return _extract_solidity(raw) or None
        except Exception:
            return None
