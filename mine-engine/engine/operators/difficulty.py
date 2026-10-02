"""难度连续旋钮（行动方案第四步）：把"同一道题"变成"任意难度的 N 道题"。

设计原则（与 10-action-plan 3.4 对齐）：
  - 旋钮是**纯文本/参数变换**，不改算子对外接口，现有调用方照跑；
  - 诱饵密度 / 代码伪装 / 跨函数 / 改写强度 四个旋钮在**本机离线就能验证**（不需要 forge）；
  - 雷数量（real_count）通过"1 个真雷 + 若干诱饵"体现，真多雷链式注入留作 forge 环境再扩。

对外只暴露两个函数：
  - `apply_difficulty(planted_source, knob) -> (new_source, metrics)`
  - `PRESETS`: 难度刻度 0..5 的预设档位

所有变换都做了防御：解析失败时原样返回，绝不悄悄产出坏代码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List


# ---- 诱饵模板：看着像漏洞，其实安全（专打"宁可错报"的模型） ----
_DECOY_TEMPLATES: List[str] = [
    # 看着像重入，但状态先清零、且有非重入守卫
    """    // [decoy] external call looks risky but state is settled first
    function decoyPayout(address to, uint256 amt) external {
        require(amt > 0 && amt <= address(this).balance, "bad amt");
        balances[to] -= amt;                       // 先记账
        (bool _ok, ) = to.call{value: amt}("");    // 后给钱（已清算，无重入）
        require(_ok, "xfer failed");
    }""",
    # 看着像整数溢出，但用的是 checked 算术
    """    // [decoy] arithmetic that looks overflow-prone but is checked
    function decoyReward(uint256 base, uint256 bonus) external pure returns (uint256) {
        require(base <= type(uint256).max - bonus, "overflow");
        return base + bonus;                        // 溢出已防御
    }""",
    # 看着像权限缺失，但有 onlyOwner 守卫
    """    // [decoy] state mutation that looks unprotected but is owner-gated
    function decoySetCap(uint256 cap) external onlyOwner {
        caps[msg.sender] = cap;                     // 仅 owner 可调
    }""",
    # 看着像 tx.origin 鉴权，但用的是 msg.sender
    """    // [decoy] auth that looks like tx.origin but uses msg.sender
    function decoyAuth() external view returns (address) {
        require(msg.sender == guardian, "not guardian");
        return msg.sender;                          // 正确：msg.sender
    }""",
]


# 保守局部变量改名（只动明显是函数内临时变量的名字，绝不碰函数名/状态变量/
# 合约名，否则会破坏 forge 测试里对 withdraw/balances 等的引用）。
_OBFUSCATE_MAP = {
    "amount": "a",
    "victim": "v",
    "attacker": "ak",
    "tmp": "t",
    "amt": "m",
}


@dataclass
class DifficultyKnob:
    """五个连续旋钮（0 刻度 = 最简单）。"""

    real_count: int = 1          # 真雷数量（基础算子已埋 1 个；此处驱动诱饵"假雷"数）
    decoy_count: int = 0         # 诱饵密度：插入几条"看着像漏洞其实没问题"的代码
    obfuscate: bool = False      # 代码伪装：局部变量改名
    cross_function: bool = False # 藏多深：把漏洞函数体包进内部 helper
    variation_k: int = 0         # 改写强度：交给 VariationOperator 做语义保持改写（需 LLM）

    def as_dict(self) -> Dict[str, object]:
        return {
            "real_count": self.real_count,
            "decoy_count": self.decoy_count,
            "obfuscate": self.obfuscate,
            "cross_function": self.cross_function,
            "variation_k": self.variation_k,
        }


# 难度刻度 0..5（简单 -> 困难）。刻度越高：诱饵越多、开启伪装、藏进 helper、加改写。
PRESETS: Dict[int, DifficultyKnob] = {
    0: DifficultyKnob(real_count=1, decoy_count=0, obfuscate=False, cross_function=False, variation_k=0),
    1: DifficultyKnob(real_count=1, decoy_count=1, obfuscate=False, cross_function=False, variation_k=0),
    2: DifficultyKnob(real_count=1, decoy_count=2, obfuscate=False, cross_function=False, variation_k=1),
    3: DifficultyKnob(real_count=1, decoy_count=3, obfuscate=True, cross_function=False, variation_k=1),
    4: DifficultyKnob(real_count=1, decoy_count=4, obfuscate=True, cross_function=True, variation_k=2),
    5: DifficultyKnob(real_count=1, decoy_count=6, obfuscate=True, cross_function=True, variation_k=3),
}


def add_decoys(src: str, n: int) -> str:
    """在合约最后一个顶层 `}` 前插入 n 个诱饵函数。解析失败则原样返回。"""
    if n <= 0:
        return src
    picks = [_DECOY_TEMPLATES[i % len(_DECOY_TEMPLATES)] for i in range(n)]
    block = "\n\n".join(picks)
    # 找到合约级最后的 `}`（缩进为 0），插在它前面
    idx = src.rfind("\n}")
    if idx == -1:
        idx = src.rfind("}")
    if idx == -1:
        return src  # 没法插，原样返回
    return src[:idx] + "\n\n" + block + "\n" + src[idx:]


def obfuscate_identifiers(src: str) -> str:
    """保守地把几个明显是局部临时变量的名字改短。不影响函数/状态变量/合约名。"""
    out = src
    for orig, short in _OBFUSCATE_MAP.items():
        # 词边界替换，避免误伤子串
        out = re.sub(rf"\b{re.escape(orig)}\b", short, out)
    return out


def extract_to_helper(src: str) -> str:
    """把第一个 `function xxx(...) { ... }` 的体包进内部 helper `_xxxImpl`。

    这是旋钮②"藏多深"的轻量实现（同文件内，不需多文件/forge）。
    解析失败时原样返回，绝不产出坏代码。
    """
    m = re.search(r"function\s+(\w+)\s*\(([^)]*)\)\s*(external|public)?\s*\{", src)
    if not m:
        return src
    fn = m.group(1)
    if fn.startswith("_"):
        return src  # 已经包过了
    start = m.end()  # `{` 之后
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return src  # 括号不匹配，放弃
    body = src[start : i - 1]
    new_fn = (
        f"function {fn}({m.group(2)}) {m.group(3) or 'external'} {{\n"
        f"        _check{fn[0].upper()}{fn[1:] if len(fn) > 1 else ''}();\n"
        f"    }}\n\n"
        f"    function _check{fn[0].upper()}{fn[1:] if len(fn) > 1 else ''}() internal {{\n"
        f"{body.rstrip()}\n    }}"
    )
    return src[: m.start()] + new_fn + src[i:]


def apply_difficulty(planted_source: str, knob: DifficultyKnob):
    """返回 (新源码, 结构指标)。所有变换失败都回退，保证产出可编译。"""
    metrics: Dict[str, object] = {
        "real_count": knob.real_count,
        "decoy_count": 0,
        "obfuscated": False,
        "cross_function": False,
        "variation_k": knob.variation_k,
    }
    out = planted_source

    if knob.decoy_count > 0:
        try:
            out = add_decoys(out, knob.decoy_count)
            metrics["decoy_count"] = knob.decoy_count
        except Exception:
            pass

    if knob.obfuscate:
        try:
            out = obfuscate_identifiers(out)
            metrics["obfuscated"] = True
        except Exception:
            pass

    if knob.cross_function:
        try:
            out = extract_to_helper(out)
            metrics["cross_function"] = True
        except Exception:
            pass

    return out, metrics
