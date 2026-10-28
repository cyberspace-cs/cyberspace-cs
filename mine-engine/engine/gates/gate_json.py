"""Gate 1: JSON Parse gate.

模型输出必须能解析成合法 JSON，且包含 findings 数组。
不过 → 整题 0 分。
"""

from __future__ import annotations

import json
import re
from typing import Any


def gate_json_parse(raw: str) -> tuple[bool, dict, str]:
    """尝试把模型输出解析成 JSON。

    返回 (passed, parsed, reason)
    - passed: True/False
    - parsed: 解析后的 dict（失败时为空 dict）
    - reason: 失败原因（成功时为空）
    """
    if not raw or not raw.strip():
        return False, {}, "empty output"

    text = raw.strip()

    # 模型经常包 ```json ... ```，先剥掉
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 再找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return False, {}, f"json parse error: {e}"

    if not isinstance(data, dict):
        return False, {}, f"expected object, got {type(data).__name__}"

    findings = data.get("findings")
    if findings is None:
        return False, {}, "missing 'findings' field"

    if not isinstance(findings, list):
        return False, {}, f"'findings' must be list, got {type(findings).__name__}"

    return True, data, ""
