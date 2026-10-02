"""离线体检：难度旋钮产出的 Solidity 是否"看起来能编译"。

为什么不直接用 forge：本机没装 solc/forge，而 CI 跑一次 forge 很慢。
这里做**静态自洽性检查**，抓的是最常见、也最致命的一类错误 ——
旋钮插进去的代码引用了不存在的状态变量/修饰符，或者括号没配平。
这类错误一旦漏到 harness，**整批样本全废**，所以必须在提交前拦住。

检查项：
  1. 括号 / 花括号配平（插入位置算错会立刻破坏结构）
  2. 诱饵依赖的符号都有声明（状态变量、modifier、事件）
  3. 诱饵函数名不重复（刻度 >4 时模板循环复用，可能产生重名函数 -> 编译错）
  4. 源码里不出现诱饵身份泄漏词

用法：
  python run_difficulty_lint.py
  python run_difficulty_lint.py --sample sample-0001
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.operators.difficulty import (  # noqa: E402
    DECOY_FUNCTIONS,
    PRESETS,
    apply_difficulty,
)

# 诱饵身份泄漏词：出现即说明伪装失败
LEAK_WORDS = ("decoy", "looks risky", "already guarded", "but is checked",
              "owner-gated", "无害", "诱饵")


def strip_comments_strings(src: str) -> str:
    """粗略去掉注释与字符串，避免注释里的括号干扰配平检查。"""
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r'"(?:[^"\\]|\\.)*"', '""', src)
    return src


def check_balanced(src: str) -> list[str]:
    """花括号/圆括号配平检查。"""
    errs = []
    s = strip_comments_strings(src)
    for open_c, close_c, name in (("{", "}", "花括号"), ("(", ")", "圆括号")):
        if s.count(open_c) != s.count(close_c):
            errs.append(f"{name}不配平：{open_c}×{s.count(open_c)} vs {close_c}×{s.count(close_c)}")
    return errs


def declared_symbols(src: str) -> set[str]:
    """粗略收集合约里已声明的符号名。"""
    names = set()
    # 状态变量：<type> ... <name> ;
    for m in re.finditer(r"^\s*(?:mapping\s*\([^)]*\)\s*)?[\w\[\]]+\s+(?:public|private|internal|constant|immutable|\s)*(\w+)\s*;",
                         src, re.M):
        names.add(m.group(1))
    # modifier / function / event / struct / contract
    for m in re.finditer(r"\b(?:modifier|function|event|struct|contract|enum)\s+(\w+)", src):
        names.add(m.group(1))
    return names


def used_identifiers(src: str) -> set[str]:
    """收集被"使用"的标识符（粗略：排除关键字与 Solidity 内建）。"""
    builtin = {
        "require", "assert", "revert", "emit", "msg", "block", "tx", "now",
        "this", "super", "address", "uint", "uint256", "int", "int256", "bool",
        "bytes", "string", "mapping", "memory", "storage", "calldata", "payable",
        "returns", "return", "if", "else", "for", "while", "break", "continue",
        "true", "false", "type", "keccak256", "abi", "external", "public",
        "internal", "private", "pure", "view", "constant", "pragma", "solidity",
        "contract", "function", "modifier", "event", "struct", "enum", "mapping",
        "selfdestruct", "new", "delete", "unchecked", "assembly",
    }
    return {w for w in re.findall(r"\b[A-Za-z_]\w*\b", src) if w not in builtin}


def check_decoy_deps(src: str, decoy_fns: list[str]) -> list[str]:
    """诱饵依赖的符号（状态变量/修饰符）是否都有声明。"""
    if not decoy_fns:
        return []
    declared = declared_symbols(src)
    errs = []
    # 只检查诱饵函数体里出现的、且是我们已知依赖的符号
    known_deps = {"partnerShare", "riskCap", "operator", "owner", "onlyOwner",
                  "guardian", "caps", "balances"}
    for fn in decoy_fns:
        m = re.search(rf"function\s+{re.escape(fn)}\s*\([^)]*\)[^{{]*\{{(.*?)\n    \}}", src, re.S)
        if not m:
            errs.append(f"找不到诱饵函数 {fn} 的函数体（插入可能被破坏）")
            continue
        body = m.group(1)
        for sym in re.findall(r"\b[A-Za-z_]\w*\b", body):
            if sym in known_deps and sym not in declared:
                errs.append(f"诱饵 {fn} 使用了未声明的符号 `{sym}` -> 编译会失败")
    return errs


def check_dup_functions(src: str) -> list[str]:
    """同名函数出现两次 -> 编译错。"""
    names = re.findall(r"\bfunction\s+(\w+)\s*\(", src)
    seen, dups = set(), set()
    for n in names:
        if n in seen:
            dups.add(n)
        seen.add(n)
    return [f"函数 `{n}` 重复定义 -> 编译会失败" for n in sorted(dups)]


def check_leak(src: str) -> list[str]:
    low = src.lower()
    return [f"源码出现泄漏词 `{w}`：诱饵自曝身份，模型会直接跳过"
            for w in LEAK_WORDS if w in low]


def load_samples(ds: Path, ids: list[str]):
    out = {}
    for sid in ids:
        pdir = ds / sid / "planted"
        if not pdir.exists():
            continue
        sols = list(pdir.glob("*.sol"))
        if sols:
            out[sid] = sols[0].read_text(encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="sample-0001,sample-0002,sample-0003")
    ap.add_argument("--out", default="results_difficulty_lint.json")
    args = ap.parse_args()

    ds = ROOT / "datasets"
    ids = [s.strip() for s in args.samples.split(",") if s.strip()]
    samples = load_samples(ds, ids)
    if not samples:
        print(f"⚠️  {ds} 下没找到样本，只用内置最小合约自测")
        samples = {"<builtin>": (
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
        )}

    all_errs = []
    n_checks = 0
    print("=" * 84)
    print(f"难度旋钮静态体检 · {len(samples)} 个样本 × 刻度 0..5")
    print("=" * 84)
    for sid, base in samples.items():
        for level in range(0, 6):
            out, metrics = apply_difficulty(base, PRESETS[level])
            errs: list[str] = []
            errs += check_balanced(out)
            errs += check_decoy_deps(out, metrics.get("decoy_functions") or [])
            errs += check_dup_functions(out)
            if level > 0:
                errs += check_leak(out)
            n_checks += 1
            flag = "OK " if not errs else "FAIL"
            print(f"[{flag}] {sid:<14} 刻度{level}  诱饵={metrics['decoy_count']} "
                  f"伪装={int(bool(metrics['obfuscated']))} 跨函数={int(bool(metrics['cross_function']))}"
                  + ("" if not errs else "  <- " + "; ".join(errs)))
            for e in errs:
                all_errs.append({"sample": sid, "level": level, "error": e})

    (ROOT / args.out).write_text(
        json.dumps({"checks": n_checks, "errors": all_errs}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("-" * 84)
    if all_errs:
        print(f"❌ {n_checks} 项检查中 {len(all_errs)} 处问题，详见 {args.out}")
        return 1
    print(f"✅ {n_checks} 项检查全部通过（括号配平 / 依赖声明 / 无重名 / 无自曝）")
    print("⚠️  注意：这是**静态**检查，不等于真的能编译。")
    print("    forge 差分验证仍是最终关口（本机无 forge，留 CI）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
