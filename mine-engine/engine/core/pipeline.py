"""DataFlow 风格的最小内核：Pipeline / Operator 与四个领域无关组件抽象。"""

from __future__ import annotations

from typing import Any, Dict, List

Record = Dict[str, Any]


class Operator:
    """一个算子：接收一批记录，返回处理后的一批记录。

    对齐 DataFlow 的 Operator 概念（其 run(storage, input_key, output_key)
    由 storage 管理数据、step 推进）。这里用零依赖的内存列表实现等价语义。
    """

    name: str = "operator"

    def __init__(self, **config: Any) -> None:
        for key, value in config.items():
            setattr(self, key, value)

    def run(self, records: List[Record]) -> List[Record]:
        raise NotImplementedError

    def __call__(self, records: List[Record]) -> List[Record]:
        return self.run(records)


class Pipeline:
    """顺序串联多个 operator，前一个的输出即后一个的输入。"""

    def __init__(self, operators: List[Operator], name: str = "pipeline") -> None:
        self.name = name
        self.operators = list(operators)

    def run(self, records: List[Record]) -> List[Record]:
        for operator in self.operators:
            records = operator.run(records)
        return list(records)


# ---------------------------------------------------------------------------
# 注入漏洞引擎的四个领域无关组件抽象（新增领域时实现这些接口即可）
# ---------------------------------------------------------------------------
class ArtifactGenerator(Operator):
    """生成或加载“健康基准体”（干净、可正常工作的材料）。"""


class IssueOperator(Operator):
    """在种子程序上注入一个已知问题，并产出 ground truth 标注。"""


class IssueValidator(Operator):
    """差分验证：问题在注入版上可被 PoC 触发，在健康版上不能，
    且材料原有功能测试仍然通过。"""


class ReportScorer(Operator):
    """把被测审计 Agent 产出的报告对 ground truth 判 recall / precision / F1。"""
