"""第三步（自我修正循环）+ 第四步（难度旋钮）离线自测。

不需要 forge、不需要 API key。覆盖：
  - 难度旋钮：刻度↑ => chaff数单调递增、高刻度开启伪装/跨函数；apply_difficulty 永不抛异常
  - 自我修正：变体首次验证失败 -> fix_variant 被调用 -> 重试后收敛；retry_count 被正确记录

用法：python run_implementation_smoke.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.operators.difficulty import PRESETS, apply_difficulty  # noqa: E402
from engine.operators.variation import VariationOperator  # noqa: E402


# ----- 假的 LLM 客户端（只用于离线测自我修正循环） -----
class FakeClient:
    def __init__(self, fix_returns_valid: bool = True):
        self.fix_returns_valid = fix_returns_valid
        self.fix_calls = 0

    def chat(self, messages, max_tokens=1024):
        # 生成阶段：返回一段看起来像合约但故意缺结尾（会被验证器判无效）
        system = messages[0]["content"]
        if "修复器" in system:  # FIX_SYSTEM 含"修复器"
            self.fix_calls += 1
            if self.fix_returns_valid:
                return "```solidity\npragma solidity ^0.8.0;\ncontract C { function f() public {} }\n```"
            return "not a solidity file"
        # 生成阶段
        return "```solidity\npragma solidity ^0.8.0;\ncontract C { function f() public {"


# ----- 假的验证器：第一次 invalid（带报错），第二次 valid -----
class FakeValidator:
    def __init__(self):
        self._seen = {}

    def run(self, records):
        for rec in records:
            key = rec["sample_id"]
            n = self._seen.get(key, 0)
            self._seen[key] = n + 1
            if n == 0:
                rec["valid"] = False
                rec["validation_log"] = "Error: Undeclared identifier 'balances' (forge test failed)"
            else:
                rec["valid"] = True
                rec["validation_log"] = ""
        return records


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"❌ FAIL: {msg}")
    print(f"  ✅ {msg}")


def test_difficulty_knob() -> None:
    print("\n[难度旋钮]")
    base = (
        "pragma solidity ^0.8.0;\n"
        "contract Vault {\n"
        "    mapping(address => uint256) balances;\n"
        "    function withdraw() external {\n"
        "        uint256 amount = balances[msg.sender];\n"
        "        balances[msg.sender] = 0;\n"
        "        (bool ok, ) = msg.sender.call{value: amount}(\"\");\n"
        "        require(ok, \"xfer failed\");\n"
        "    }\n"
        "}\n"
    )
    prev_decoys = -1
    for level in range(0, 6):
        knob = PRESETS[level]
        out, metrics = apply_difficulty(base, knob)
        # 变换要真的生效：chaff 函数名出现在产物里
        if metrics["decoy_count"]:
            _assert(all(fn in out for fn in metrics["decoy_functions"]),
                    f"刻度{level} chaff 函数确实插入到源码里")
        _assert(metrics["decoy_count"] >= prev_decoys,
                f"刻度{level} chaff数({metrics['decoy_count']}) >= 上一档({prev_decoys}) [单调]")
        prev_decoys = metrics["decoy_count"]
    # 高刻度应开启伪装 + 跨函数
    _, m5 = apply_difficulty(base, PRESETS[5])
    _, m0 = apply_difficulty(base, PRESETS[0])
    _assert(m5["obfuscated"] and m5["cross_function"], "刻度5 开启伪装+跨函数")
    _assert(not m0["obfuscated"] and not m0["cross_function"], "刻度0 不开启伪装/跨函数")
    _assert(m5["decoy_count"] > m0["decoy_count"], "刻度5 chaff数 > 刻度0")
    # 跨函数变换应把 withdraw 包进 helper
    out5, _ = apply_difficulty(base, PRESETS[5])
    _assert("_checkWithdraw" in out5, "跨函数变换生成了内部 helper _checkWithdraw")

    # ---- 两条硬规则（都是实跑踩出来的）----
    # 规则1：chaff 绝不能自曝身份。函数名/注释里出现 decoy/safe 之类词就等于告诉模型
    #        "这段是示意代码"，模型直接跳过，难度旋钮退化成"只加长度不加难度"。
    out_d, _ = apply_difficulty(base, PRESETS[5])
    low = out_d.lower()
    leaked = [w for w in ("decoy", "[decoy]", "looks risky", "already guarded",
                          "but is checked", "owner-gated") if w in low]
    _assert(not leaked, f"chaff 不得自曝身份（发现泄漏词: {leaked}）")

    # 规则2：插入的chaff 必须能编译 —— 依赖的状态/修饰符要先补齐。
    out_c, _ = apply_difficulty(base, PRESETS[4])
    for sym in ("partnerShare", "onlyOwner", "operator", "riskCap"):
        if sym in out_c:
            _assert(out_c.count(sym) >= 2 or sym in ("onlyOwner",),
                    f"{sym} 既被使用也应有声明")
    _assert("modifier onlyOwner()" in out_c or "onlyOwner" not in out_c,
            "用到 onlyOwner 就必须补上 modifier 定义")
    _assert("mapping(address => uint256) internal partnerShare;" in out_c,
            "缺失的状态变量声明已自动补齐")
    # 幂等：再插一次不应重复声明
    twice, _ = apply_difficulty(out_c, PRESETS[4])
    _assert(twice.count("internal partnerShare;") == 1, "状态声明注入是幂等的")

    # 规则3：chaff 函数名必须唯一。模板只有 4 条而刻度 5 要插 6 个，
    #       直接循环复用会产出同名函数重复定义 —— Solidity 编译错误，整批样本全废。
    fns5 = m5["decoy_functions"]
    _assert(len(fns5) == len(set(fns5)), f"刻度5 chaff 函数名不重复: {fns5}")
    _assert(len(fns5) == 6, f"刻度5 应规划 6 个chaff，实际 {len(fns5)}")
    defined = re.findall(r"\bfunction\s+(\w+)\s*\(", out_d)
    dups = {x for x in defined if defined.count(x) > 1}
    _assert(not dups, f"插入后无重名函数（发现 {dups}）")
    # 依赖声明也要去重：多个chaff可能都依赖 partnerShare
    _assert(out_d.count("internal partnerShare;") == 1,
            f"依赖声明去重（实际出现 {out_d.count('internal partnerShare;')} 次）")



def test_self_correction() -> None:
    print("\n[自我修正循环]")
    client = FakeClient(fix_returns_valid=True)
    vary = VariationOperator(client, k=1)
    validator = FakeValidator()

    rec = {"sample_id": "sample-x", "planted_source": "contract C { function f() public {",
           "issues": [{"vuln_type": "reentrancy"}]}
    # 模拟 run() 产出一个变体
    variants = vary.run([rec])
    v = [r for r in variants if r.get("variation")][0]

    # 复刻 batch_generate 里的重试循环
    current = v
    attempts = 0
    max_retries = 2
    while attempts <= max_retries:
        vmap = {r["sample_id"]: r for r in validator.run([current])}
        checked = vmap.get(current["sample_id"], current)
        if checked.get("valid"):
            current = checked
            break
        attempts += 1
        fixed = vary.fix_variant(checked, checked.get("validation_log", ""))
        assert fixed is not None
        current = {**current, "planted_source": fixed}
    current["retry_count"] = attempts

    _assert(current.get("valid"), "重试后变体通过验证")
    _assert(attempts == 1, f"恰好重试 1 次即收敛（实际 {attempts}）")
    _assert(current["retry_count"] == 1, "retry_count 记录为 1")
    _assert(client.fix_calls == 1, "fix_variant 被调用了 1 次")


def main() -> None:
    print("=" * 70)
    print("第三步 + 第四步 离线自测")
    print("=" * 70)
    test_difficulty_knob()
    test_self_correction()
    print("\n✅ 全部通过")


if __name__ == "__main__":
    main()
