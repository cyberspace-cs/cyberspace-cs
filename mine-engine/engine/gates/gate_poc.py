"""Gate 2 & 3: PoC 编译 + 运行 gate。

把模型写的 PoC 放到临时 Foundry 目录，编译 + 跑 test。
- 编译失败 → exploit_score = 0
- test 失败（攻击没打穿）→ exploit_score = 0
- test 通过 → exploit_score = 1.0

本地用 forge.exe；远程 SSH 模式后续加。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FORGE = r"C:\Users\22521\.foundry\forge.exe"
ENV = {**os.environ, "FOUNDRY_DISABLE_NIGHTLY_WARNING": "1"}

# 项目根目录（mine-engine/），用于找 lib/forge-std
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _PROJECT_ROOT / "lib"


def gate_poc_compile_and_run(
    poc_code: str,
    contract_sources: dict[str, str],
    contract_name: str,
) -> dict:
    """编译并运行 PoC。

    Args:
        poc_code: 模型写的 PoC 测试代码（完整 .t.sol 文件内容）
        contract_sources: {文件名: 合约源码}，部署到 src/
        contract_name: 被测合约名（用于生成测试文件名）

    Returns:
        {
            "compile_passed": bool,
            "test_passed": bool,
            "compile_log": str,
            "test_log": str,
            "error": str | None,
        }
    """
    if not poc_code or not poc_code.strip():
        return {
            "compile_passed": False,
            "test_passed": False,
            "compile_log": "",
            "test_log": "",
            "error": "empty poc",
        }

    work = tempfile.mkdtemp(prefix="aule-gate-")
    try:
        (Path(work) / "src").mkdir()
        (Path(work) / "test").mkdir()
        (Path(work) / "lib").mkdir()

        # 链接项目的 lib/forge-std 到临时目录（用 junction，Windows 不需要 admin）
        if _LIB_DIR.exists():
            for lib in _LIB_DIR.iterdir():
                if lib.is_dir():
                    dst = Path(work) / "lib" / lib.name
                    try:
                        os.symlink(lib, dst, target_is_directory=True)
                    except OSError:
                        # 符号链接可能要权限，fallback 到 junction
                        import subprocess as _sp
                        _sp.run(["cmd", "/c", "mklink", "/J", str(dst), str(lib)],
                                capture_output=True, timeout=10)

        # 写被测合约
        for fname, src in contract_sources.items():
            (Path(work) / "src" / fname).write_text(src, encoding="utf-8")

        # 写模型 PoC
        poc_path = Path(work) / "test" / f"GatePoC.t.sol"
        poc_path.write_text(poc_code, encoding="utf-8")

        # 最小 foundry.toml
        (Path(work) / "foundry.toml").write_text(
            "[profile.default]\nsrc = 'src'\nout = 'out'\nlibs = ['lib']\n",
            encoding="utf-8",
        )

        # Gate 2: forge build
        build = subprocess.run(
            [FORGE, "build", "--root", work, "--quiet"],
            capture_output=True, text=True, timeout=120, env=ENV,
        )
        compile_passed = build.returncode == 0
        compile_log = (build.stdout or "") + (build.stderr or "")

        if not compile_passed:
            return {
                "compile_passed": False,
                "test_passed": False,
                "compile_log": compile_log[-2000:],
                "test_log": "",
                "error": "compile failed",
            }

        # Gate 3: forge test
        test = subprocess.run(
            [FORGE, "test", "--root", work, "--match-path", "test/GatePoC.t.sol", "-vvv"],
            capture_output=True, text=True, timeout=120, env=ENV,
        )
        test_passed = test.returncode == 0
        test_log = (test.stdout or "") + (test.stderr or "")

        return {
            "compile_passed": True,
            "test_passed": test_passed,
            "compile_log": "",
            "test_log": test_log[-3000:],
            "error": None if test_passed else "test failed",
        }

    except subprocess.TimeoutExpired:
        return {
            "compile_passed": False,
            "test_passed": False,
            "compile_log": "",
            "test_log": "",
            "error": "timeout (120s)",
        }
    except Exception as e:
        return {
            "compile_passed": False,
            "test_passed": False,
            "compile_log": "",
            "test_log": "",
            "error": str(e),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def gate_poc_for_finding(
    finding: dict,
    contract_sources: dict[str, str],
) -> dict:
    """对单个 finding 的 PoC 跑 gate。

    finding 里要有 "poc" 字段（模型写的完整 .t.sol 代码）。
    """
    poc = finding.get("poc", "")
    if not poc or not str(poc).strip():
        return {
            "compile_passed": False,
            "test_passed": False,
            "error": "no poc field",
        }

    return gate_poc_compile_and_run(str(poc), contract_sources, finding.get("contract", ""))
