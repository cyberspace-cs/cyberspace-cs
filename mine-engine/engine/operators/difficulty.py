"""难度连续旋钮（行动方案第四步）：把"同一道题"变成"任意难度的 N 道题"。

设计原则（与 docs/10-action-plan.md 3.4 对齐）：
  - 旋钮是**纯文本/参数变换**，不改算子对外接口，现有调用方照跑；
  - 诱饵密度 / 代码伪装 / 跨函数 / 改写强度 四个旋钮在**本机离线就能验证**（不需要 forge）；
  - 雷数量（real_count）通过"1 个真雷 + 若干诱饵"体现，真多雷链式注入留作 forge 环境再扩。

两条踩过坑才写下来的硬规则（改这个文件前先读）：
  1. **诱饵绝不能自曝身份**。函数名不能叫 `decoyXxx`，注释里不能出现
     "decoy / safe / already guarded" 这类词。真实工程里攻击者不会给代码写批注
     说明自己无害——一旦自曝，模型会直接跳过，诱饵的欺骗性归零，
     难度旋钮就变成"只加长度不加难度"（实测 F1 反而会上升）。
  2. **诱饵必须能编译**。插入的函数只能引用"保证存在"的状态变量；
     缺的声明要先补上（见 `ensure_state_decls`），否则 forge 一跑就炸，
     整批样本全废。

对外只暴露：
  - `apply_difficulty(planted_source, knob) -> (new_source, metrics)`
  - `PRESETS`: 难度刻度 0..5 的预设档位
  - `DECOY_FUNCTIONS`: 诱饵函数名清单（供统计"模型有没有踩雷"）

所有变换都做了防御：解析失败时原样返回，绝不悄悄产出坏代码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List


# ---- 诱饵模板：看着像漏洞，其实安全（专打"宁可错报"的模型） ----
#
# 每条 = (基础函数名, 依赖声明列表, 代码模板)。
# 代码模板里用 `{fn}` 占位函数名：模板只有 4 条，但刻度 5 要插 6 个诱饵，
# 直接循环复用会产出**同名函数重复定义**（Solidity 编译直接失败，整批样本全废）。
# 所以插入时按轮次给函数名加区分后缀（payoutPartner / payoutPartner2 / ...），
# 既避免重名，也更贴近真实项目里"同类逻辑有多个入口"的形态。
#
# ⚠️ 依赖声明也必须**按最终函数名去重**（不同诱饵可能依赖同一个状态变量）。
_DECOY_TEMPLATES: List[tuple[str, List[str], str]] = [
    # ① 看着像重入：外部调用在最后、且状态已结算
    (
        "payoutPartner",
        ["    mapping(address => uint256) internal partnerShare;"],
        """    // settle the affiliate share before paying out
    function {fn}(address to, uint256 amt) external {{
        require(amt > 0 && amt <= partnerShare[msg.sender], "bad amt");
        partnerShare[msg.sender] -= amt;
        (bool _ok, ) = to.call{{value: amt}}("");
        require(_ok, "xfer failed");
    }}""",
    ),
    # ② 看着像溢出：其实有 require 守卫（无外部依赖）
    (
        "accrueTier",
        [],
        """    // accrue tier bonus for an account
    function {fn}(uint256 base, uint256 bonus) external pure returns (uint256) {{
        require(base <= type(uint256).max - bonus, "overflow");
        return base + bonus;
    }}""",
    ),
    # ③ 看着像权限缺失：其实 onlyOwner（modifier 与 owner 都要补）
    (
        "setRiskCap",
        [
            "    address internal owner;",
            "    mapping(address => uint256) internal riskCap;",
            "    modifier onlyOwner() { require(msg.sender == owner, \"not owner\"); _; }",
        ],
        """    // set the per-account risk cap
    function {fn}(uint256 cap) external onlyOwner {{
        riskCap[msg.sender] = cap;
    }}""",
    ),
    # ④ 看着像 tx.origin 鉴权：其实用 msg.sender
    (
        "maintenanceMode",
        ["    address internal operator;"],
        """    // operator-gated maintenance entry
    function {fn}() external view returns (bool) {{
        require(msg.sender == operator, "not operator");
        return true;
    }}""",
    ),
]

# 诱饵**基础**函数名（实际插入时可能带 2/3 后缀去重，见 plan_decoys）
# 保留这个常量是为了让调用方不必读模板就能知道"可能插入哪些函数"。
DECOY_FUNCTIONS: List[str] = [
    "payoutPartner", "accrueTier", "setRiskCap", "maintenanceMode",
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
    # ⚠️ 改写强度：**目前只是名义值，apply_difficulty 并不会真的调用 LLM 改写。**
    #    它需要 VariationOperator（要配 API key、每次几秒到几十秒），属于离线旋钮之外的
    #    另一档开销，所以扫描表里刻度 2..5 显示的"改写x1/x2/x3"目前**不代表实际难度增量**。
    #    接线方式见 apply_difficulty 的注释。诚实起见先不假装它生效。
    variation_k: int = 0

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


def ensure_state_decls(src: str, decls: List[str]) -> str:
    """把缺失的状态变量/修饰符声明补到合约体开头，保证插入的诱饵能编译。

    幂等：已存在同名符号就跳过。只在能定位到 `contract X {` 时动手，否则原样返回。
    """
    m = re.search(r"contract\s+\w+[^{]*\{", src)
    if not m:
        return src
    body = src[m.end():]
    added = []
    for d in decls:
        if not d.strip():
            continue
        # 取声明里最后那个标识符作为符号名（跳过末尾的 ";" / "{...}"）
        sym = d.split()[-1].rstrip(";").strip()
        if sym and re.search(rf"\b{re.escape(sym)}\b", body):
            continue
        added.append(d)
    if not added:
        return src
    return src[: m.end()] + "\n" + "\n".join(added) + "\n" + src[m.end():]


def plan_decoys(n: int) -> list[tuple[str, List[str], str]]:
    """规划要插入的 n 个诱饵，返回 [(最终函数名, 依赖声明, 渲染后的代码)]。

    函数名去重：模板只有 4 条，第 5 个开始按 `name2 / name3` 加后缀，
    否则同名函数重复定义在 Solidity 里是**编译错误**（刻度 5 要插 6 个，必踩）。
    """
    out: list[tuple[str, List[str], str]] = []
    used: set[str] = set()
    for i in range(n):
        base, decls, tpl = _DECOY_TEMPLATES[i % len(_DECOY_TEMPLATES)]
        name = base
        k = 2
        while name in used:
            name = f"{base}{k}"
            k += 1
        used.add(name)
        out.append((name, decls, tpl.format(fn=name)))
    return out


def add_decoys(src: str, n: int) -> str:
    """在合约最后一个顶层 `}` 前插入 n 个诱饵函数（并补齐它们需要的状态声明）。"""
    if n <= 0:
        return src
    plan = plan_decoys(n)
    # 依赖声明去重（不同诱饵可能依赖同一状态变量）
    decls, seen = [], set()
    for _, ds, _ in plan:
        for d in ds:
            if d not in seen:
                seen.add(d)
                decls.append(d)
    body = "\n\n".join(code for _, _, code in plan)

    src = ensure_state_decls(src, decls)

    # 找到合约级最后的 `}`（缩进为 0），插在它前面
    idx = src.rfind("\n}")
    if idx == -1:
        idx = src.rfind("}")
    if idx == -1:
        return src  # 没法插，原样返回
    return src[:idx] + "\n\n" + body + "\n" + src[idx:]


def obfuscate_identifiers(src: str) -> str:
    """保守地把几个明显是局部临时变量的名字改短。不影响函数/状态变量/合约名。"""
    out = src
    for orig, short in _OBFUSCATE_MAP.items():
        # 词边界替换，避免误伤子串；但不能改掉我们刚插入的诱饵函数名
        out = re.sub(rf"(?<![\w]){re.escape(orig)}\b", short, out)
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
        # 新增：实际插入的诱饵函数名，供统计踩雷率
        "decoy_functions": [],
    }
    out = planted_source

    if knob.decoy_count > 0:
        try:
            before = len(out)
            out = add_decoys(out, knob.decoy_count)
            if len(out) > before:
                metrics["decoy_count"] = knob.decoy_count
                metrics["decoy_functions"] = [fn for fn, _, _ in plan_decoys(knob.decoy_count)]
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

    # ⚠️ variation_k 故意不执行：它要真调 LLM（VariationOperator），是"离线旋钮"之外的
    #    另一档开销（每题几秒到几十秒 + 花钱）。这里如实标 false，扫描表会显示
    #    "改写未接线"而不是假装难度已经上去了。
    #    要接线时：把 client/variation_operator 传进来，调
    #    `VariationOperator(client, k=knob.variation_k).run([{...'planted_source': out...}])`，
    #    并**把改写后的源码作为新输入**（不能只记个数）。
    metrics["variation_applied"] = False

    return out, metrics
