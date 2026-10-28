"""模型单价表与成本估算（零第三方依赖）。

⚠️ 设计原则：**绝不编造单价**。

各供应商的定价随时在变，而且网关/私有化部署的口径各不相同。
这里**不内置任何"我记得大概是"的价格**——编一个数字比没有数字更危险，
因为它会让成本那一列看起来很有道理，实际上是假的。

所以：
- 内置表默认为空，单价必须显式配置（环境变量或 JSON 文件）
- 未配置时 `estimate_cost()` 返回 **None**，调用方应显示为 "n/a" 并给出警告
  —— 注意 None 与 0.0 是两回事：**0.0 表示"确实免费/自部署"，None 表示"不知道"**
- 支持按模型名精确匹配，也支持环境变量覆盖

配置方式（二选一，环境变量优先）：
    # 1) 环境变量，JSON 字符串，单位 USD / 每百万 token
    $env:LLM_PRICES='{"qwen3.8-flash":{"in":0.2,"out":2.0},"deepseek-v4-flash":{"in":0.28,"out":0.42}}'

    # 2) 仓库根目录下 prices.json（已在 .gitignore 中，不上传）
    {"qwen3.8-flash": {"in": 0.2, "out": 2.0}}

字段名认 in/out 与 input/output 两种写法。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

_PER_MILLION = 1_000_000.0


def _normalise(raw: Dict) -> Dict[str, Dict[str, float]]:
    """把用户配置规整成 {model: {"in": x, "out": y}}。"""
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(raw, dict):
        return out
    for model, spec in raw.items():
        if isinstance(spec, (int, float)):
            # 简写：只给一个数，视为输入输出同价
            out[str(model)] = {"in": float(spec), "out": float(spec)}
            continue
        if not isinstance(spec, dict):
            continue
        tin = spec.get("in", spec.get("input", spec.get("input_per_mtok")))
        tout = spec.get("out", spec.get("output", spec.get("output_per_mtok")))
        if tin is None or tout is None:
            continue
        try:
            out[str(model)] = {"in": float(tin), "out": float(tout)}
        except (TypeError, ValueError):
            continue
    return out


def _load_file(path: Path) -> Dict[str, Dict[str, float]]:
    try:
        if not path.exists():
            return {}
        return _normalise(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


class PriceTable:
    def __init__(self, prices: Dict[str, Dict[str, float]] | None = None,
                 configured: bool = False):
        self.prices: Dict[str, Dict[str, float]] = prices or {}
        # configured=False 表示"用户没配过"，此时任何查询都应返回 None
        self.configured = configured

    @classmethod
    def load(cls, root: Path | None = None) -> "PriceTable":
        """环境变量 LLM_PRICES 优先，其次根目录 prices.json。"""
        env = os.environ.get("LLM_PRICES", "").strip()
        if env:
            try:
                return cls(_normalise(json.loads(env)), configured=True)
            except json.JSONDecodeError:
                # 配错了要让人知道，而不是静默当成没配
                raise ValueError("LLM_PRICES 不是合法 JSON，请检查引号与逗号")
        root = root or Path(__file__).resolve().parents[2]
        table = _load_file(root / "prices.json")
        return cls(table, configured=bool(table))

    def get(self, model: str) -> Optional[Dict[str, float]]:
        if not self.configured:
            return None
        if model in self.prices:
            return self.prices[model]
        # 前缀匹配：应对 "qwen3.8-max-2026-01" 这类带后缀的名字
        best = None
        for name, spec in self.prices.items():
            if model.startswith(name):
                if best is None or len(name) > len(best[0]):
                    best = (name, spec)
        return best[1] if best else None

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> Optional[float]:
        """返回 USD。未配置单价返回 None（不是 0）。"""
        spec = self.get(model)
        if spec is None:
            return None
        cost = tokens_in / _PER_MILLION * spec["in"] + tokens_out / _PER_MILLION * spec["out"]
        return round(cost, 6)


def cost_per_solved_task(total_cost: Optional[float], n_solved: int) -> Optional[float]:
    """ALE-Bench 口径的成本指标：分母只算做对的题。

    小红书 Muse 的原话：一个便宜的配置如果需要重试三次再由人改一遍，
    其实它并不便宜。所以分母必须是"成功数"而不是"尝试数"。

    成功数为 0 时返回 None（无穷大，无法用有限数字表示），调用方应显示为 n/a。
    """
    if total_cost is None or n_solved <= 0:
        return None
    return round(total_cost / n_solved, 6)
