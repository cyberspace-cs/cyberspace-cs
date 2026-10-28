"""IssueValidator：基于 Foundry 的差分验证（领域无关、支持任意算子）。

对每条样本：
  1) 按 planted_contract_name 找到手写“黄金版”，做归一化等价比较
     （忽略注释与空白，只比代码结构）；
  2) 临时用算子输出覆盖该黄金文件，运行 `forge test`：
       必须全部通过 —— happy-path 全过、健康版攻击失败、注入版攻击成功；
  3) 无论成功与否，恢复黄金文件。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from ..core.pipeline import IssueValidator


def _strip_comments(src: str) -> str:
    """移除每行中字符串字面量之外的 // 行注释。"""
    out = []
    for line in src.splitlines():
        in_string = False
        escaped = False
        cut = len(line)
        for i, ch in enumerate(line):
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
            if not in_string and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def normalize_source(src: str) -> str:
    """归一化为可比较的紧凑代码：去注释、去全部空白。"""
    return re.sub(r"\s+", "", _strip_comments(src))


class FoundryDiffValidator(IssueValidator):
    name = "foundry-diff-validator"

    def __init__(self, root, forge_exe: str = "forge", **config):
        super().__init__(**config)
        self.root = Path(root)
        self.forge = forge_exe

    def _golden_path(self, planted_contract_name: str) -> Path:
        return self.root / "src" / "planted" / f"{planted_contract_name}.sol"

    def _run_forge(self):
        env = dict(os.environ)
        env["FOUNDRY_DISABLE_NIGHTLY_WARNING"] = "1"
        proc = subprocess.run(
            [self.forge, "test", "--root", str(self.root)],
            capture_output=True,
            text=True,
            env=env,
        )
        log = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and "0 failed" in log
        return ok, log

    def run(self, records):
        for rec in records:
            golden_path = self._golden_path(rec["planted_contract_name"])
            golden = golden_path.read_text(encoding="utf-8")

            rec["matches_golden"] = (
                normalize_source(rec["planted_source"]) == normalize_source(golden)
            )
            try:
                golden_path.write_text(rec["planted_source"], encoding="utf-8")
                ok, log = self._run_forge()
                rec["valid"] = ok
                rec["validation_log"] = log.strip()
            finally:
                # 始终恢复手写黄金文件
                golden_path.write_text(golden, encoding="utf-8")
        return records
