"""OpenAI 兼容 Chat 客户端（零第三方依赖，urllib 实现）。

配置全部来自环境变量，绝不硬编码密钥：
    LLM_BASE_URL   例如 https://dashscope.aliyuncs.com/compatible-mode/v1
    LLM_API_KEY    密钥
    LLM_MODEL      默认模型名

M7+ 变更：把 API 返回的 usage 透传出来。
此前 `chat()` 只返回回答文本，usage 被整个丢掉，导致成本无从计算
（见 docs/10-action-plan.md 3.1 —— 这是"记时间与钱"这一步的硬阻塞）。

向后兼容：`chat()` 仍返回 str，现有调用方一行都不用改。
需要 token 数的调用方改用 `chat_detailed()`，或读 `client.last_response`。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict


class LLMError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# usage 提取：各供应商字段名不一致，这里认常见的几种
# ---------------------------------------------------------------------------
_IN_KEYS = ("prompt_tokens", "input_tokens", "input_token_count", "prompt_token_count")
_OUT_KEYS = ("completion_tokens", "output_tokens", "output_token_count",
             "completion_token_count")


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class LLMResponse:
    """一次调用的全部产出：文本 + 用量 + 耗时。"""
    text: str
    usage: Usage
    model: str
    latency_ms: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "tokens_in": self.usage.tokens_in,
            "tokens_out": self.usage.tokens_out,
            "tokens_total": self.usage.total,
            "model": self.model,
            "latency_ms": self.latency_ms,
        }


def _pick(d: Dict[str, Any], keys) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
        # 有些供应商返回字符串
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    return 0


def extract_usage(data: Dict[str, Any]) -> Usage:
    """从 API 响应里取 usage。取不到就返回全 0，并在 raw 里留证。"""
    u = data.get("usage")
    if not isinstance(u, dict):
        # 少数网关把用量平铺在顶层
        u = data if any(k in data for k in _IN_KEYS + _OUT_KEYS) else {}
    return Usage(
        tokens_in=_pick(u, _IN_KEYS),
        tokens_out=_pick(u, _OUT_KEYS),
        raw=dict(u) if isinstance(u, dict) else {},
    )


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, temperature: float = 0.0,
                 timeout: int = 120, fake=None):
        self.base_url = (base_url or os.environ["LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.model = model or os.environ.get("LLM_MODEL", "qwen3.8-flash")
        self.temperature = temperature
        self.timeout = timeout
        # fake: 可选的 (messages) -> (text, usage_dict) 回调，仅用于离线自测/演示。
        # 生产路径不设置它；有了它就不用真调 API 也能验证记账链路。
        self.fake = fake
        self.last_response: LLMResponse | None = None
        self.calls: int = 0
        self.total_usage = Usage()

    # -- 底层：真正的一次调用 -------------------------------------------------
    def _request(self, body: bytes) -> Dict[str, Any]:
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # -- 对外两个入口 ---------------------------------------------------------
    def chat_detailed(self, messages, max_tokens: int = 1024, retries: int = 2) -> LLMResponse:
        """返回 LLMResponse（含 token 用量与耗时）。"""
        if self.fake is not None:
            t0 = time.time()
            text, usage_d = self.fake(messages)
            resp = LLMResponse(
                text=text or "",
                usage=Usage(
                    tokens_in=_pick(usage_d, _IN_KEYS),
                    tokens_out=_pick(usage_d, _OUT_KEYS),
                    raw=dict(usage_d),
                ),
                model=self.model,
                latency_ms=int((time.time() - t0) * 1000),
            )
            self._record(resp)
            return resp

        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")

        last_err = None
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                data = self._request(body)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                raise LLMError(f"HTTP {e.code}: {detail[:500]}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e
                if attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise LLMError(f"network after {retries+1} tries: {last_err}") from e

            resp = LLMResponse(
                text=(data.get("choices") or [{}])[0].get("message", {}).get("content") or "",
                usage=extract_usage(data),
                model=data.get("model", self.model),
                latency_ms=int((time.time() - t0) * 1000),
            )
            self._record(resp)
            return resp

        raise LLMError(f"network after {retries+1} tries: {last_err}")

    def chat(self, messages, max_tokens: int = 1024, retries: int = 2) -> str:
        """向后兼容入口：只返回文本。用量可从 self.last_response 取。"""
        return self.chat_detailed(messages, max_tokens=max_tokens, retries=retries).text

    # -- 记账 -----------------------------------------------------------------
    def _record(self, resp: LLMResponse) -> None:
        self.last_response = resp
        self.calls += 1
        self.total_usage.tokens_in += resp.usage.tokens_in
        self.total_usage.tokens_out += resp.usage.tokens_out

    def usage_summary(self) -> Dict[str, Any]:
        """整个客户端生命周期内的累计用量。"""
        return {
            "calls": self.calls,
            "tokens_in": self.total_usage.tokens_in,
            "tokens_out": self.total_usage.tokens_out,
            "tokens_total": self.total_usage.total,
            "model": self.model,
        }
