"""Centralized scoring rule definitions — weights, thresholds, and deduction factors for all dimensions.

This file is the "single source of truth" for the scoring system: any scoring
adjustment should only be made here. Dimension processors (dimensions/) reference
constants from this module and must not hard-code numeric values in function bodies.

Note: Modifying any constant affects historical score comparability; changes
require evaluation and code review.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 成功率（success_rate）—— 三个子维度加权平均
# ---------------------------------------------------------------------------

# 首次生成成功率权重（核心指标，始终参与计算）
SUCCESS_RATE_INITIAL_GENERATION_WEIGHT = 0.6
# 问题修复成功率权重（预留，仅在有值时参与，动态归一化）
SUCCESS_RATE_ISSUE_FIX_WEIGHT = 0.2
# 补充需求成功率权重（预留，仅在有值时参与，动态归一化）
SUCCESS_RATE_REQUIREMENT_EXTENSION_WEIGHT = 0.2

# ---------------------------------------------------------------------------
# 质量（quality）—— 减法扣分模式
# 公式: 功能完整性 = 用例完整性 - 稳定性扣分 - 后端完整性扣分
# ---------------------------------------------------------------------------

# 稳定性扣分系数: (1 - stability/100) × 用例完整性 × 该系数
QUALITY_STABILITY_DEDUCTION_RATIO = 0.2
# 后端完整性扣分系数: (1 - backend/100) × 用例完整性 × 该系数
QUALITY_BACKEND_DEDUCTION_RATIO = 0.3

# 用例完整性 reason 分档阈值（通过比例）
QUALITY_USECASE_MOSTLY_PASS_RATIO = 0.75  # 高于此为"大部分通过"
QUALITY_USECASE_PARTIAL_PASS_RATIO = 0.5  # 高于此为"部分未实现"

# 后端通过率 reason 分档阈值
BACKEND_PASS_RATE_FULL = 1.0   # 全部通过
BACKEND_PASS_RATE_MOSTLY = 0.8  # 大部分通过
BACKEND_PASS_RATE_PARTIAL = 0.5  # 部分通过

# ---------------------------------------------------------------------------
# 体验（experience）—— 动态权重归一化
# 基准权重: 耗时 60% + 包大小 20% + 美观度 20%；Token 仅展示不参与。
# 包大小仅在有数据时参与（小程序/H5 无包大小）；美观度仅在有截图评分时参与；
# 缺失维度不计入，剩余维度权重自动归一化到 1.0。
# ---------------------------------------------------------------------------

EXPERIENCE_DURATION_WEIGHT = 0.6
EXPERIENCE_PACKAGE_SIZE_WEIGHT = 0.2
EXPERIENCE_AESTHETICS_WEIGHT = 0.2

# 耗时 reason 分档（基于耗时得分）
EXPERIENCE_DURATION_EXCELLENT_SCORE = 90  # ≥ 此分为"优秀"
EXPERIENCE_DURATION_GOOD_SCORE = 75       # ≥ 此分为"良好"
EXPERIENCE_DURATION_FAIR_SCORE = 60       # ≥ 此分为"一般"，低于为"较慢"

# ---------------------------------------------------------------------------
# 耗时（duration）—— 分段线性递减
# ≤ excellent: 100 分；excellent~30min: 100→5 分；30min~poor: 5→0 分；≥ poor: 0 分
# ---------------------------------------------------------------------------

# 各阶段默认阈值 (excellent_ms, poor_ms)，可被样本 threshold_config 覆盖
DURATION_DEFAULT_THRESHOLDS: dict[str, tuple[int, int]] = {
    "total": (120_000, 3_600_000),  # 2 分钟优秀，60 分钟差
}

# 总耗时超时阈值（毫秒），超过即标记 is_timeout
DURATION_DEFAULT_TIMEOUT_MS = 1_800_000  # 30 分钟

# 分段线性的中间拐点（毫秒）与拐点分值
DURATION_MID_THRESHOLD_MS = 1_800_000  # 30 分钟
DURATION_MID_SCORE = 5.0  # 拐点处分值：excellent~拐点 100→5，拐点~poor 5→0

# ---------------------------------------------------------------------------
# 包大小（package_size）—— 分档线性插值（针对移动应用）
# ---------------------------------------------------------------------------

_MB = 1024 * 1024
# 阈值区间: (上界字节数, 区间起始分(下界处分值), 区间分值跨度)
# 边界值: 0MB=100, 10MB=80, 30MB=60, 60MB=40, 100MB=20, >100MB=20
PACKAGE_SIZE_THRESHOLDS: list[tuple[int, float, float]] = [
    (10 * _MB, 100.0, 20.0),   # 0MB:100 → 10MB:80
    (30 * _MB, 80.0, 20.0),    # 10MB:80 → 30MB:60
    (60 * _MB, 60.0, 20.0),    # 30MB:60 → 60MB:40
    (100 * _MB, 40.0, 20.0),   # 60MB:40 → 100MB:20
]
# 超过最大阈值后的保底分
PACKAGE_SIZE_FLOOR_SCORE = 20.0

# 包大小 reason 分档（基于包大小得分）
PACKAGE_SIZE_EXCELLENT_SCORE = 90
PACKAGE_SIZE_GOOD_SCORE = 70
PACKAGE_SIZE_FAIR_SCORE = 50

# ---------------------------------------------------------------------------
# 稳定性（stability）
# score = max(0, 1 - issue_rate) × 100
# issue_rate = (crash + anr + white_screen) / total_test_runs
# ---------------------------------------------------------------------------
# （公式无可调常量；reason 分档见下）

# 稳定性 reason 分档（基于稳定性得分）
STABILITY_MINOR_ISSUE_SCORE = 80   # ≥ 此分为"偶发问题不影响主流程"
STABILITY_NOTABLE_ISSUE_SCORE = 60  # ≥ 此分为"存在明显问题"，低于为"严重"

# ---------------------------------------------------------------------------
# 功能覆盖（core function coverage，V2 doc 3.2）
# ---------------------------------------------------------------------------

# failed（存在但坏了）比 missing 更糟，按 failed 占比额外扣分
FUNCTIONALITY_FAILED_PENALTY = 15.0

# ---------------------------------------------------------------------------
# 代码质量（code_quality，V2 doc 3.3）—— 规则分部分（80% 权重来源）
# ---------------------------------------------------------------------------

# 三个子指标权重
CODE_QUALITY_STATIC_SCAN_WEIGHT = 0.40   # 静态扫描/规约符合度（P0）
CODE_QUALITY_COMPLEXITY_WEIGHT = 0.30    # 圈复杂度（P1）
CODE_QUALITY_DUPLICATION_WEIGHT = 0.30   # 重复代码率（P1）

# 静态扫描惩罚模型：error 每个扣 5 分，warning 每个扣 1 分；规约符合率最高加 20 分
CODE_QUALITY_ERROR_PENALTY = 5.0
CODE_QUALITY_WARNING_PENALTY = 1.0
CODE_QUALITY_COMPLIANCE_BONUS_MAX = 20.0

# 复杂度无数据时的中性分
CODE_QUALITY_NEUTRAL_SCORE = 70.0
# 高复杂度函数占比惩罚上限（占比 × 该系数）
CODE_QUALITY_HIGH_COMPLEXITY_PENALTY = 30.0
