"""极简 .env 加载器（零第三方依赖）。

为什么需要它：所有脚本都从环境变量读密钥（`LLM_BASE_URL` / `LLM_API_KEY` ...），
但每次开终端都要手动 export 一遍，忘了就报 KeyError。一个 .env 文件能省掉这件事。

规则（与常见 dotenv 一致）：
- 只认 `KEY=VALUE`，`#` 开头为注释，空行忽略
- VALUE 两侧的单/双引号会被剥掉，支持行内 `#` 之后的注释（仅当未被引号包裹时切）
- **已存在的环境变量优先**：终端里 export 的值不会被 .env 覆盖，
  这样临时换网关跑一次实验不用改文件

用法：
    from engine.llm import load_dotenv
    load_dotenv()          # 从仓库根目录找 .env
    load_dotenv(ROOT)      # 传目录也行，自动补 .env
"""

from __future__ import annotations

import os
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_line(line: str):
    """解析一行，返回 (key, value) 或 None（注释/空行/非法行）。"""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("export "):
        s = s[len("export "):].strip()
    if "=" not in s:
        return None
    key, _, val = s.partition("=")
    key = key.strip()
    if not key:
        return None
    val = val.strip()
    # 未被引号包裹时，`#` 之后是注释
    if val and val[0] not in ("'", '"'):
        if " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        elif val.startswith("#"):
            val = ""
    elif len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    return key, val


def load_dotenv(path: str | Path | None = None, override: bool = False) -> int:
    """把 .env 里的变量写进 os.environ，返回写入条数。文件不存在返回 0。

    `path` 可以是 .env 文件本身，**也可以是它所在的目录**（目录则自动补 `.env`）。
    两种都支持是有必要的：脚本里手上通常只有 `ROOT = Path(__file__).parent`，
    直接传目录最自然，而早期版本只认文件，传目录会因为
    `Path.exists()` 对目录为真而走到 `read_text()` 抛 PermissionError。
    """
    p = Path(path) if path else _root() / ".env"
    if p.is_dir():
        p = p / ".env"
    if not p.is_file():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        kv = parse_line(line)
        if not kv:
            continue
        key, val = kv
        if not override and key in os.environ:
            continue
        os.environ[key] = val
        n += 1
    return n
