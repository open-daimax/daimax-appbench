"""评分维度处理器 —— 每个模块对应一个评测维度的计分逻辑。

规则常量统一定义在 ``..rules``，本包只承载计分公式与 reason 文案生成。
"""

from .backend import score_backend_completeness
from .code_quality import score_code_quality
from .duration import compute_duration_statistics, score_duration
from .experience import compute_experience
from .functionality import score_core_function_coverage, score_state_handling
from .package_size import format_size_display, generate_package_size_reason, score_package_size
from .quality import compute_quality
from .stability import score_stability
from .success_rate import compute_success_rate

__all__ = [
    "compute_duration_statistics",
    "compute_experience",
    "compute_quality",
    "compute_success_rate",
    "format_size_display",
    "generate_package_size_reason",
    "score_backend_completeness",
    "score_code_quality",
    "score_core_function_coverage",
    "score_duration",
    "score_package_size",
    "score_stability",
    "score_state_handling",
]
