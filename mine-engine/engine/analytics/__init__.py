"""评测分析：难度 / 区分度 / 抗污染性 / 环境四维质量（零第三方依赖）。

两块：
- difficulty.py   —— 评模型：难度、IRT(Rasch)、区分度、CRS 抗污染、重复统计
- env_quality.py  —— 评考场：正确性、多样性、复杂性、忠实度 + 去重与类别上限

理论依据：arXiv:2606.12191（环境四维评价）、arXiv:2606.05405（AWM，blocked rate / 类别上限）。
"""

from .difficulty import (
    RaschResult,
    contamination_resistance,
    crs_summary,
    fit_rasch,
    item_difficulty,
    item_discrimination,
    pass_rate,
    summarize_repeats,
)

from .env_quality import (
    DiversityReport,
    QualityReport,
    blocked_rate,
    category_cap_check,
    category_distribution,
    ceiling_floor_check,
    dedup_by_embedding,
    difficulty_histogram,
    diversity_score,
    env_quality_report,
    structural_signature,
)

__all__ = [
    # difficulty
    "RaschResult",
    "contamination_resistance",
    "crs_summary",
    "fit_rasch",
    "item_difficulty",
    "item_discrimination",
    "pass_rate",
    "summarize_repeats",
    # env_quality
    "DiversityReport",
    "QualityReport",
    "blocked_rate",
    "category_cap_check",
    "category_distribution",
    "ceiling_floor_check",
    "dedup_by_embedding",
    "difficulty_histogram",
    "diversity_score",
    "env_quality_report",
    "structural_signature",
]
