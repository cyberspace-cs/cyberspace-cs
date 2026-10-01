"""OpenAI 兼容 Chat 客户端（零第三方依赖，urllib 实现）。

配置全部来自环境变量，绝不硬编码密钥：
    LLM_BASE_URL   例如 https://dashscope.aliyuncs.com/compatible-mode/v1
    LLM_API_KEY    密钥
    LLM_MODEL      默认模型名

M7+ 补充（真实模型跑通后新增）：
    LLM_MAX_TOKENS  单次最大输出 token（默认 4096）
    LLM_THINKING    on/off，控制 DeepSeek 的 thinking 模式（不设则沿用服务端默认）

⚠️ 为什么默认从 1024 提到 4096：
    thinking 模型会先在 reasoning 里烧 token，烧完才吐正式回答。实测 deepseek-v4-pro
    在 max_tokens=1024 下 reasoning 就吃满了预算，content 返回**空字符串**，
    HTTP 状态码是 200、usage 也完整——从外面看一切都"正常"，只是分数悄悄变成 0。
    这类"看起来正常的失败"比报错危险得多，所以客户端现在会显式识别它（truncated）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import warnings

from dataclasses import dataclass, field
from typing import Any, Dict


class LLMError(RuntimeError):
    pass


class LLMTruncatedWarning(UserWarning):
    """模型返回了空答案（多为 thinking 预算被吃满），但不报错——必须让人看见。"""


# 单次回答的默认 token 上限。1024 对 thinking 模型不够，见模块 docstring。
DEFAULT_MAX_TOKENS = 4096


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
    # 两个细分字段：deepseek 这类网关会把「命中缓存的输入」和「思考链」单独报价，
    # 命中缓存的输入单价可能便宜几十倍，记下来才能算准（算不准就按贵的报，不占便宜）。
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class LLMResponse:
    """一次调用的全部产出：文本 + 用量 + 耗时 + 有没有被截断。"""
    text: str
    usage: Usage
    model: str
    latency_ms: int = 0
    finish_reason: str = ""
    # True 表示"答案很可能是空的，而且不是模型不会答，是预算不够"
    truncated: bool = False

    @property
    def empty_text(self) -> bool:
        return not self.text.strip()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "tokens_in": self.usage.tokens_in,
            "tokens_out": self.usage.tokens_out,
            "tokens_total": self.usage.total,
            "cached_tokens": self.usage.cached_tokens,
            "reasoning_tokens": self.usage.reasoning_tokens,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "truncated": self.truncated,
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


def _dig(d: Dict[str, Any], *paths) -> int:
    """按多层字段取值，取不到就 0。各供应商把细分用量放在不同嵌套里。"""
    for path in paths:
        cur: Any = d
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and isinstance(cur, (int, float)) and not isinstance(cur, bool):
            return int(cur)
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
        cached_tokens=_dig(u, ("prompt_tokens_details", "cached_tokens"),
                           ("input_tokens_details", "cached_tokens"),
                           ("cache_read_input_tokens",)),
        reasoning_tokens=_dig(u, ("completion_tokens_details", "reasoning_tokens"),
                              ("output_tokens_details", "reasoning_tokens")),
        raw=dict(u) if isinstance(u, dict) else {},
    )


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, temperature: float = 0.0,
                 timeout: int = 120, fake=None, max_tokens: int = DEFAULT_MAX_TOKENS,
                 thinking: str | None = None, strict: bool = False):
        self.base_url = (base_url or os.environ["LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.model = model or os.environ.get("LLM_MODEL", "qwen3.8-flash")
        self.temperature = temperature
        self.timeout = timeout
        # 单次回答的 token 上限。thinking 模型要在 reasoning 上先花掉几百到几千个，
        # 1024 会被吃干导致答案为空（见模块 docstring 里的实踩记录）。
        self.max_tokens = max_tokens
        # thinking: None=沿用服务端默认；"on"/"off" 显式开关（DeepSeek 用 {"thinking":{"type":...}}）
        self.thinking = thinking
        # strict=True：拿到截断的空答案时直接抛错，而不是悄悄返回空串
        self.strict = strict
        # fake: 可选的 (messages) -> (text, usage_dict) 回调，仅用于离线自测/演示。
        # 生产路径不设置它；有了它就不用真调 API 也能验证记账链路。
        self.fake = fake
        self.last_response: LLMResponse | None = None
        self.calls: int = 0
        self.total_usage = Usage()
        # 记账：空答案 / 截断次数。跑完 benchmark 必须回头看这两个数是否为 0
        self.empty_text_calls: int = 0
        self.truncated_calls: int = 0

    @classmethod
    def from_env(cls, model: str | None = None, **kwargs) -> "LLMClient":
        """按环境变量建客户端，把散落的配置集中到一个地方。

        认的变量：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_TEMPERATURE
                  LLM_MAX_TOKENS / LLM_THINKING
        """
        if "base_url" not in kwargs:
            kwargs["base_url"] = os.environ["LLM_BASE_URL"]
        if "api_key" not in kwargs:
            kwargs["api_key"] = os.environ["LLM_API_KEY"]
        return cls(
            model=model or os.environ.get("LLM_MODEL"),
            temperature=float(os.environ.get("LLM_TEMPERATURE", "0") or 0),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
            thinking=os.environ.get("LLM_THINKING") or None,
            **kwargs,
        )

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
    def chat_detailed(self, messages, max_tokens: int | None = None,
                      retries: int = 2) -> LLMResponse:
        """返回 LLMResponse（含 token 用量与耗时）。

        max_tokens 不传就用 client 默认值（LLM_MAX_TOKENS，默认 4096）。
        """
        mt = max_tokens or self.max_tokens
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

        body_map: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": mt,
        }
        if self.thinking in ("on", "enabled", "true", "1"):
            body_map["thinking"] = {"type": "enabled"}
        elif self.thinking in ("off", "disabled", "false", "0", "none"):
            body_map["thinking"] = {"type": "disabled"}
        body = json.dumps(body_map).encode("utf-8")

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

            choice = (data.get("choices") or [{}])[0]
            finish = choice.get("finish_reason") or ""
            usage = extract_usage(data)
            resp = LLMResponse(
                text=choice.get("message", {}).get("content") or "",
                usage=usage,
                model=data.get("model", self.model),
                latency_ms=int((time.time() - t0) * 1000),
                finish_reason=finish,
            )
            # 截断判定：答案为空，且 finish_reason=length，或输出 token 已经贴着上限
            if resp.empty_text and (finish == "length" or usage.tokens_out >= mt * 0.98):
                resp.truncated = True
                self.truncated_calls += 1
                msg = (f"模型 {resp.model} 返回空答案且疑似被 token 上限截断"
                       f"（finish_reason={finish or '空'}, 输出 {usage.tokens_out}/{mt} token，"
                       f"其中思考链 {usage.reasoning_tokens}）。"
                       f"提高 LLM_MAX_TOKENS 或关掉 thinking（LLM_THINKING=off）再试。"
                       f"⚠️ 这类失败 HTTP 状态码是 200，不报错，只会让分数悄悄变 0。")
                if self.strict:
                    raise LLMError(msg)
                warnings.warn(msg, LLMTruncatedWarning, stacklevel=2)
            self._record(resp)
            return resp

        raise LLMError(f"network after {retries+1} tries: {last_err}")

    def chat(self, messages, max_tokens: int | None = None, retries: int = 2) -> str:
        """向后兼容入口：只返回文本。用量可从 self.last_response 取。"""
        return self.chat_detailed(messages, max_tokens=max_tokens, retries=retries).text

    # -- 记账 -----------------------------------------------------------------
    def _record(self, resp: LLMResponse) -> None:
        self.last_response = resp
        self.calls += 1
        self.total_usage.tokens_in += resp.usage.tokens_in
        self.total_usage.tokens_out += resp.usage.tokens_out
        self.total_usage.cached_tokens += resp.usage.cached_tokens
        self.total_usage.reasoning_tokens += resp.usage.reasoning_tokens
        if resp.empty_text:
            self.empty_text_calls += 1

    def usage_summary(self) -> Dict[str, Any]:
        """整个客户端生命周期内的累计用量。"""
        return {
            "calls": self.calls,
            "tokens_in": self.total_usage.tokens_in,
            "tokens_out": self.total_usage.tokens_out,
            "tokens_total": self.total_usage.total,
            "cached_tokens": self.total_usage.cached_tokens,
            "reasoning_tokens": self.total_usage.reasoning_tokens,
            "model": self.model,
            # 这两个数不为 0 就是有样本被静默吞了，结果不可信
            "empty_text_calls": self.empty_text_calls,
            "truncated_calls": self.truncated_calls,
        }
