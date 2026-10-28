"""评测分析：难度 / 区分度 / 抗污染性 / 环境四维质量（零第三方依赖）。

三块：
- difficulty.py   —— 评模型：难度、IRT(Rasch)、区分度、CRS 抗污染、重复统计
- env_quality.py  —— 评考场：正确性、多样性、复杂性、忠实度 + 去重与类别上限
- openended.py    —— 评上限：时间轴、成本轴、饱和检测、Performance 归一化

理论依据：
- arXiv:2606.12191（中科院自动化所，环境四维评价）
- arXiv:2602.10090（AWM，blocked rate / 类别上限；UNC + Snowflake, ICML'26）
- arXiv:2506.09050（ALE-Bench，连续分 / 时间轴 / 成本轴 / Performance；Sakana × AtCoder）
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

from .openended import (
    budget_report,
    cost_quality_frontier,
    long_horizon_curve,
    performance_elo,
    rank_percentile,
    saturation_check,
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
    # openended
    "budget_report",
    "cost_quality_frontier",
    "long_horizon_curve",
    "performance_elo",
    "rank_percentile",
    "saturation_check",
]
