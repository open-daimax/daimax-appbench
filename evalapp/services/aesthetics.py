"""统一美观度评分服务 - 消除 evaluate.py 和 reporting.py 中的重复逻辑。

提供单一入口来执行美观度评测，并将结果写入 scores.json。
evaluate 阶段和 report 阶段共用此模块，避免 DRY 违反。
"""

from pathlib import Path
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


def load_rules(rules_path: Optional[Path] = None) -> Optional[dict]:
    """美观度评分规则（兼容旧接口）。

    新版纯 Python 实现不再依赖 yaml 规则文件，但保留此函数
    以兼容调用方的 truthiness 检查（rules is not None → 可执行评分）。
    """
    return {"version": "1.0"}


def _build_model_config(config=None, model_name: str | None = None):
    """构建美观度评分模型配置。

    优先级：显式 model_name > config.models.aesthetics > 环境变量 > 硬编码默认值
    """
    import os
    from ..evaluation.metrics.collectors.aesthetics_scorer import ModelConfig

    cfg_aes = None
    if config is not None:
        cfg_aes = config.models.aesthetics
    else:
        try:
            from ..config import get_config
            cfg_aes = get_config().models.aesthetics
        except Exception:
            pass

    if cfg_aes is not None:
        return ModelConfig(
            base_url=cfg_aes.base_url or os.environ.get("AESTHETICS_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=cfg_aes.api_key or os.environ.get("DASHSCOPE_API_KEY", ""),
            name=(model_name or cfg_aes.name) or os.environ.get("AESTHETICS_MODEL", "qwen-vl-max"),
        )

    # 无 config 兜底：纯环境变量 → 硬编码默认值
    return ModelConfig(
        base_url=os.environ.get("AESTHETICS_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        name=model_name or os.environ.get("AESTHETICS_MODEL", "qwen-vl-max"),
    )


def score_sample(
    workspace: Path,
    sample_id: str,
    platform: str,
    app_category: str = "",
    rules: Optional[dict] = None,
    model: str | None = None,
    config=None,
) -> Optional[dict]:
    """对单个样本执行美观度评分。

    这是美观度评分的统一入口，evaluate 和 report 阶段都调用此函数。

    Args:
        workspace: 工作区路径
        sample_id: 样本ID
        platform: 平台名称
        app_category: 应用类别（用于规则匹配）
        rules: 已弃用，保留以兼容旧调用方
        model: 指定评分模型名称（如 qwen-vl-max），优先级高于 config
        config: EvalApp Config 对象，为 None 时尝试 get_config() 全局单例

    Returns:
        评分结果字典 (含 overall, comment, issues, dimensions, rule_version, scored_frames)，
        评分失败或无截图时返回 None
    """
    from ..evaluation.metrics.collectors.aesthetics import score_aesthetics

    sample_dir = workspace / sample_id

    # 构造模型配置：config 字段优先 → 环境变量 → 硬编码兜底
    model_config = _build_model_config(config, model_name=model)

    try:
        result = score_aesthetics(
            sample_dir=str(sample_dir),
            platform=platform,
            app_category=app_category,
            model_config=model_config,
        )
        if result:
            return {
                "aesthetics_score": result.overall,
                "aesthetics_reason": result.comment,
                "aesthetics_issues": result.issues,
                "aesthetics_dimensions": result.dimensions,
                "aesthetics_rule_version": result.rule_version,
                "aesthetics_scored_frames": result.scored_frames,
            }
    except Exception as e:
        logger.warning("Aesthetics scoring failed for %s/%s: %s", sample_id, platform, e)

    return None


def update_scores_with_aesthetics(
    workspace: Path,
    sample_id: str,
    platform: str,
    aesthetics_data: dict,
) -> None:
    """将美观度评分结果写入 scores.json。

    Args:
        workspace: 工作区路径
        sample_id: 样本ID
        platform: 平台名称
        aesthetics_data: score_sample() 返回的结果字典
    """
    from ..workspace.sample_data import read_scores, write_scores

    scores = read_scores(workspace, sample_id) or {"sample_id": sample_id, "platforms": {}}
    if "platforms" not in scores:
        scores["platforms"] = {}
    if platform not in scores["platforms"]:
        scores["platforms"][platform] = {}

    scores["platforms"][platform].update(aesthetics_data)
    write_scores(workspace, sample_id, scores)
    logger.info(
        "Aesthetics scored %.1f/10 for %s/%s",
        aesthetics_data.get("aesthetics_score", 0), sample_id, platform,
    )


def score_and_persist(
    workspace: Path,
    sample_id: str,
    platform: str,
    app_category: str = "",
    rules: Optional[dict] = None,
    skip_if_exists: bool = False,
    config=None,
) -> Optional[dict]:
    """评分并持久化的一站式入口。

    如果 skip_if_exists=True 且 scores.json 中已有美观度分数，则跳过评测直接返回已有结果。

    Args:
        workspace: 工作区路径
        sample_id: 样本ID
        platform: 平台名称
        app_category: 应用类别
        rules: 已弃用，保留以兼容旧调用方
        skip_if_exists: 是否跳过已有结果
        config: EvalApp Config 对象，为 None 时尝试 get_config() 全局单例

    Returns:
        评分结果字典，或 None
    """
    if skip_if_exists:
        from ..workspace.sample_data import read_scores
        existing = read_scores(workspace, sample_id)
        if existing:
            existing_score = (
                existing.get("platforms", {})
                .get(platform, {})
                .get("aesthetics_score")
            )
            if existing_score is not None:
                # 已有评分，返回已有数据
                plat_data = existing["platforms"][platform]
                return {
                    "aesthetics_score": plat_data.get("aesthetics_score"),
                    "aesthetics_reason": plat_data.get("aesthetics_reason", ""),
                    "aesthetics_issues": plat_data.get("aesthetics_issues", []),
                    "aesthetics_dimensions": plat_data.get("aesthetics_dimensions", {}),
                    "aesthetics_rule_version": plat_data.get("aesthetics_rule_version", ""),
                    "aesthetics_scored_frames": plat_data.get("aesthetics_scored_frames", []),
                }

    result = score_sample(workspace, sample_id, platform, app_category, rules, config=config)
    if result:
        update_scores_with_aesthetics(workspace, sample_id, platform, result)
    return result


class AestheticsService:
    """美观度评分服务 - config-aware 封装。

    提供单一入口来执行美观度评测，evaluate 和 report 阶段共用此服务。
    模型配置优先级：config.models.aesthetics → 环境变量 → 硬编码默认值。
    """

    def __init__(self, workspace: Path, config=None):
        self.workspace = Path(workspace)
        self.config = config

    def score_sample(
        self,
        sample_id: str,
        platform: str,
        app_category: str = "",
        rules: Optional[dict] = None,
        model: str | None = None,
    ) -> Optional[dict]:
        return score_sample(
            self.workspace, sample_id, platform, app_category, rules, model, config=self.config
        )

    def score_and_persist(
        self,
        sample_id: str,
        platform: str,
        app_category: str = "",
        rules: Optional[dict] = None,
        skip_if_exists: bool = False,
    ) -> Optional[dict]:
        return score_and_persist(
            self.workspace,
            sample_id,
            platform,
            app_category,
            rules,
            skip_if_exists,
            config=self.config,
        )
