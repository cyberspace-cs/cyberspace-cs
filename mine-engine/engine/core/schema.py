"""Ground truth 标注 schema（零依赖，使用标准库 dataclasses）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Location:
    """问题在注入版材料中的位置。"""

    file: str
    function: str
    start_line: int
    end_line: int


@dataclass
class Issue:
    """一个被埋入的问题及其完整 ground truth。"""

    issue_id: str
    sample_id: str
    vuln_type: str          # 如 reentrancy
    swc: str                # 如 SWC-107
    severity: str           # critical / high / medium / low
    location: Location
    difficulty: int         # 1-5
    poc: str                # PoC 标识或路径
    discovery_hint: str
    operator: str           # 由哪个算子埋入
    seed: int

    def to_dict(self) -> dict:
        return asdict(self)
