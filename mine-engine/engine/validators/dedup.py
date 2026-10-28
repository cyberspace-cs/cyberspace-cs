"""去重 filter：把 planted 源码 normalize（去注释/空白）后算哈希，语义重复的丢弃。

对齐 DataFlow 的 filtering operator：生成阶段会产出大量变体，靠它控制数据集多样性。
"""

from __future__ import annotations

import hashlib
import re


def normalize_source(src: str) -> str:
    """去掉行注释与所有空白差异，只留结构化 token。"""
    src = re.sub(r"//[^\n]*", "", src)          # 行注释
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # 块注释
    src = re.sub(r"\s+", " ", src).strip()
    return src


def fingerprint(src: str) -> str:
    return hashlib.sha256(normalize_source(src).encode("utf-8")).hexdigest()[:16]


def dedup(records: list) -> tuple:
    """返回 (去重后保留的, 被丢弃的)。按 planted_source 的指纹去重。"""
    seen = set()
    kept, dropped = [], []
    for rec in records:
        fp = fingerprint(rec["planted_source"])
        if fp in seen:
            dropped.append(rec)
        else:
            seen.add(fp)
            kept.append(rec)
    return kept, dropped
