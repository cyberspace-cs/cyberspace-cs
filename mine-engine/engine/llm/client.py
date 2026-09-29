"""OpenAI 兼容 Chat 客户端（零第三方依赖，urllib 实现）。

配置全部来自环境变量，绝不硬编码密钥：
    LLM_BASE_URL   例如 https://dashscope.aliyuncs.com/compatible-mode/v1
    LLM_API_KEY    密钥
    LLM_MODEL      默认模型名
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, temperature: float = 0.0, timeout: int = 120):
        self.base_url = (base_url or os.environ["LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.model = model or os.environ.get("LLM_MODEL", "qwen3.8-flash")
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, messages, max_tokens: int = 1024) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise LLMError(f"HTTP {e.code}: {detail[:500]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"network: {e.reason}") from e

        return data["choices"][0]["message"]["content"] or ""
