"""体验维度：耗时 + 包大小 + 美观度动态权重归一化综合评分。"""

from __future__ import annotations

from ..models import ExperienceMetrics
from ..rules import (
    EXPERIENCE_AESTHETICS_WEIGHT,
    EXPERIENCE_DURATION_EXCELLENT_SCORE,
    EXPERIENCE_DURATION_FAIR_SCORE,
    EXPERIENCE_DURATION_GOOD_SCORE,
    EXPERIENCE_DURATION_WEIGHT,
    EXPERIENCE_PACKAGE_SIZE_WEIGHT,
)
from ....utils.logging import get_logger
from .duration import score_duration
from .package_size import generate_package_size_reason, score_package_size

logger = get_logger(__name__)


def compute_experience(
    duration_ms: int,
    package_size_bytes: int = 0,
    token_input: int = 0,
    token_output: int = 0,
    token_total: int = 0,
    aesthetics_score: float | None = None,
    aesthetics_reason: str = "",
    aesthetics_issues: list | None = None,
    aesthetics_dimensions: dict | None = None,
    aesthetics_rule_version: str = "",
    aesthetics_scored_frames: list | None = None,
    threshold_config: dict | None = None,
) -> ExperienceMetrics:
    """计算综合体验得分

    Args:
        duration_ms: 端到端耗时(毫秒)
        package_size_bytes: 构建产物大小(字节)
        token_input: 输入token数
        token_output: 输出token数
        token_total: 总token数
        aesthetics_score: UI美观度评分(0-10), None表示未评分
        aesthetics_reason: 美观度一句话评语
        aesthetics_issues: 美观度扣分明细
        aesthetics_dimensions: 美观度子维度得分
        aesthetics_rule_version: 使用的规则版本
        aesthetics_scored_frames: 评分截图相对路径
        threshold_config: 可选的阈值配置

    Returns:
        ExperienceMetrics with duration_score, package_size_score and composite_score
    """
    # 复用耗时维度的评分逻辑
    # 延迟导入以避免 metrics ↔ results 循环导入
    from ...results.models import DurationMetrics

    durations = DurationMetrics(total_ms=duration_ms)
    duration_score_obj = score_duration(durations, threshold_config)

    # 生成耗时原因
    duration_sec = duration_ms / 1000
    score = duration_score_obj.composite_score

    # 使用中文时间格式
    if duration_sec < 60:
        time_display = f"{duration_sec:.1f}秒" if duration_sec != int(duration_sec) else f"{int(duration_sec)}秒"
    else:
        minutes = int(duration_sec // 60)
        seconds = duration_sec % 60
        if seconds == 0:
            time_display = f"{minutes}分钟"
        elif seconds != int(seconds):
            time_display = f"{minutes}分{seconds:.1f}秒"
        else:
            time_display = f"{minutes}分{int(seconds)}秒"

    if score >= EXPERIENCE_DURATION_EXCELLENT_SCORE:
        duration_reason = f"生成速度优秀，耗时{time_display}"
    elif score >= EXPERIENCE_DURATION_GOOD_SCORE:
        duration_reason = f"生成速度良好，耗时{time_display}"
    elif score >= EXPERIENCE_DURATION_FAIR_SCORE:
        duration_reason = f"生成速度一般，耗时{time_display}"
    else:
        duration_reason = f"生成速度较慢，耗时{time_display}"

    # 包大小评分逻辑(基于字节数)
    package_size_score = score_package_size(package_size_bytes)
    package_size_reason = generate_package_size_reason(package_size_bytes, package_size_score)

    metrics = ExperienceMetrics(
        end_to_end_duration_ms=duration_ms,
        duration_score=duration_score_obj.composite_score,
        duration_reason=duration_reason,
        package_size_bytes=package_size_bytes,
        package_size_score=package_size_score,
        package_size_reason=package_size_reason,
        token_input=token_input,
        token_output=token_output,
        token_total=token_total,
    )

    # ── 动态权重重分配（Dynamic weight reallocation）──────────────────
    #
    # 基准权重见 rules.py：耗时60% + 包大小20% + 美观度20%，Token 仅展示不参与。
    #
    # 【触发重分配的条件】
    #   1. 某些平台无法获取包大小（如小程序 H5）→ package_size_bytes <= 0，
    #      则不计入包大小维度。
    #   2. 未提供截图或未调用美观度评分 → aesthetics_score is None，
    #      则不计入美观度维度（不使用默认值，默认值逻辑已废弃）。
    #
    # 【归一化算法】
    #   - 在 raw_weights 中仅保留参与评分的维度及其原始权重。
    #   - total_weight = sum(raw_weights.values())。
    #   - 当 total_weight > 0 时，各维度重新归一化为 w / total_weight，
    #     以保证总权重为 1.0。
    #   - 当 total_weight == 0 时（全部维度都缺失，极端场景），
    #     跳过归一化，composite_score 默认为 0.0，避免除零。
    #
    # 【各分支覆盖场景】
    #   - duration + package_size + aesthetics  → 安卓/iOS 且含截图。
    #   - duration + package_size              → 安卓/iOS 不含截图。
    #   - duration + aesthetics                → 小程序/H5 含截图。
    #   - duration                             → 小程序/H5 不含截图（仅耗时参与）。
    #   - 空                                  → 所有维度都缺失，这里不会出现
    #                                            （duration 总是会加入）。
    raw_weights = {}
    raw_weights['duration'] = EXPERIENCE_DURATION_WEIGHT
    if package_size_bytes > 0:
        raw_weights['package_size'] = EXPERIENCE_PACKAGE_SIZE_WEIGHT
    if aesthetics_score is not None:
        raw_weights['aesthetics'] = EXPERIENCE_AESTHETICS_WEIGHT  # 美观度仅在有截图数据时参与

    total_weight = sum(raw_weights.values())

    score_map = {
        'duration': metrics.duration_score,
        'package_size': metrics.package_size_score,
        'aesthetics': aesthetics_score * 10 if aesthetics_score is not None else 0.0,  # 0-10 -> 0-100
    }

    if total_weight > 0:
        # 归一化后权重总和应严格为 1.0（允许极小浮点误差）。
        normalized_weights = {k: w / total_weight for k, w in raw_weights.items()}
        weight_sum = sum(normalized_weights.values())
        # 使用 assert + warning 双重保障：在开发环境下及时暴露问题，
        # 在生产环境下也不静默。
        if not (0.999 <= weight_sum <= 1.001):
            logger.warning(
                "体验指标权重归一化后总和偏离 1.0：weight_sum=%.6f, raw_weights=%s",
                weight_sum, raw_weights,
            )
        assert 0.999 <= weight_sum <= 1.001, (
            f"权重归一化后总和必须为 1.0，实际={weight_sum}"
        )
        metrics.composite_score = round(
            sum(score_map[k] * normalized_weights[k] for k in raw_weights), 1
        )
    else:
        # 防御性分支：全部维度缺失时，避免除零并记录警告。
        logger.warning(
            "体验指标所有维度权重都为 0，无法归一化；composite_score 设为 0.0。"
        )
        metrics.composite_score = 0.0

    # 填充美观度字段
    metrics.aesthetics_score = aesthetics_score
    metrics.aesthetics_reason = aesthetics_reason
    metrics.aesthetics_issues = aesthetics_issues or []
    metrics.aesthetics_dimensions = aesthetics_dimensions or {}
    metrics.aesthetics_rule_version = aesthetics_rule_version
    metrics.aesthetics_scored_frames = aesthetics_scored_frames or []

    return metrics
