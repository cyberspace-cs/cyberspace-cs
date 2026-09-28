"""算子注册中心：把每个埋雷算子的“类型元数据 + 构造方式”登记起来。

这是从“单算子脚本”升级为“可扩展、可批量生成引擎”的关键：
新增一个漏洞算子，只需实现 IssueOperator 并在此 register，
编排层即可按 vuln_type 动态取用，不必改动 pipeline。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .access_control import AccessControlInjector
from .reentrancy import ReentrancyInjector


@dataclass
class OperatorSpec:
    vuln_type: str
    swc: str
    severity: str
    target_contract: str       # 该算子作用于哪个健康合约
    injector_cls: type         # IssueOperator 子类
    default_difficulty: int


class OperatorRegistry:
    def __init__(self) -> None:
        self._specs: dict = {}

    def register(self, spec: OperatorSpec) -> "OperatorRegistry":
        self._specs[spec.vuln_type] = spec
        return self

    def get(self, vuln_type: str) -> OperatorSpec:
        if vuln_type not in self._specs:
            raise KeyError(f"未注册的算子: {vuln_type}")
        return self._specs[vuln_type]

    def types(self) -> List[str]:
        return list(self._specs)

    def specs(self) -> List[OperatorSpec]:
        return list(self._specs.values())

    def build_injector(self, vuln_type: str, **config):
        spec = self.get(vuln_type)
        return spec.injector_cls(**config)


def default_registry() -> OperatorRegistry:
    registry = OperatorRegistry()
    registry.register(
        OperatorSpec(
            vuln_type="reentrancy",
            swc="SWC-107",
            severity="critical",
            target_contract="Vault",
            injector_cls=ReentrancyInjector,
            default_difficulty=2,
        )
    )
    registry.register(
        OperatorSpec(
            vuln_type="access_control",
            swc="SWC-105",
            severity="high",
            target_contract="Ownable",
            injector_cls=AccessControlInjector,
            default_difficulty=1,
        )
    )
    return registry
