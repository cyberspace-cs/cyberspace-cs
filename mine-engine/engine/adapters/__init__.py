"""赛道 adapter 层。

四组件抽象（Generator / Operator / Validator / Scorer）是领域无关的；
本包负责两件事：
  1. 把生成的样本导出为 Harbor 任务三元组（instruction + sandbox + verifier）
  2. 定义国家审计 / 企业审计 / 审计师三条赛道的 adapter 契约
"""

from .domains import (
    DOMAIN_REGISTRY,
    AuditDomainSpec,
    get_domain,
    list_domains,
)
from .harbor import (
    ExportStats,
    export_dataset,
    export_harbor_task,
)

__all__ = [
    "DOMAIN_REGISTRY",
    "AuditDomainSpec",
    "get_domain",
    "list_domains",
    "ExportStats",
    "export_dataset",
    "export_harbor_task",
]
