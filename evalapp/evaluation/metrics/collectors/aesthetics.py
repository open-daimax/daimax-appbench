"""美观度评分 - 入口编排模块。

协调帧选取、VL 模型评分和结果持久化。
替代原有的 Go 子进程调用方式，使用纯 Python 实现。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .aesthetics_frames import select_key_frames
from .aesthetics_scorer import ModelConfig, ScoringResult, score_frames

logger = logging.getLogger(__name__)


@dataclass
class AestheticsResult:
    """美观度评分结果（保持与原有接口兼容）。"""
    overall: float  # 0-10 综合分
    rule_version: str  # 使用的规则版本
    dimensions: dict  # 子维度得分 {name: score}
    comment: str  # 一句话总结
    issues: list[str]  # 扣分明细
    scored_frames: list[str]  # 参与评分的截图相对路径（相对于 sample_dir）
    penalized_frames: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0


def score_aesthetics(
    sample_dir: str,
    platform: str,
    app_category: str = "",
    model_config: ModelConfig | None = None,
) -> AestheticsResult | None:
    """执行美观度评分。

    Args:
        sample_dir: 样本目录绝对路径（其下应含 screenshots/）
        platform: 平台标识（expo_web / ios / miniprogram 等）
        app_category: 应用品类（可选）
        model_config: 模型配置（base_url, api_key, name），为 None 时从环境获取

    Returns:
        AestheticsResult 评分结果；无截图时返回 None
    """
    # 1. 选取关键帧
    frames = select_key_frames(sample_dir, platform)
    if not frames:
        logger.info("美观度评分跳过：%s 无可用截图", sample_dir)
        return None

    # 2. 确保模型配置
    if model_config is None:
        model_config = _default_model_config()

    # 3. 调用 VL 模型评分
    error_msg: str | None = None
    scoring_result: ScoringResult | None = None

    try:
        scoring_result = score_frames(frames, app_category, model_config)
    except Exception as e:
        error_msg = str(e)
        logger.error("美观度评分失败 %s/%s: %s", sample_dir, platform, e)

    # 4. 写 trace 文件（无论成功/失败都写）
    _write_trace(
        sample_dir=sample_dir,
        platform=platform,
        frames=frames,
        model_config=model_config,
        scoring_result=scoring_result,
        error=error_msg,
    )

    # 5. 组装返回结果
    if scoring_result is None:
        return None

    return AestheticsResult(
        overall=scoring_result.overall,
        rule_version=scoring_result.rule_version,
        dimensions=scoring_result.dimensions,
        comment=scoring_result.comment,
        issues=scoring_result.issues,
        scored_frames=scoring_result.scored_frames,
        penalized_frames=scoring_result.penalized_frames,
        usage=scoring_result.usage,
        cost_usd=scoring_result.cost_usd,
    )


def _default_model_config() -> ModelConfig:
    """从环境变量获取默认模型配置（last-resort 兜底）。

    优先级：调用方传入 config.models.aesthetics > 环境变量 > 硬编码默认值。
    本函数仅在调用方未提供 model_config 时使用（env var → hardcoded）。
    """
    import os
    return ModelConfig(
        base_url=os.environ.get("AESTHETICS_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=os.environ.get("DASHSCOPE_API_KEY") or "",
        name=os.environ.get("AESTHETICS_MODEL") or "qwen-vl-max",
    )


def _write_trace(
    sample_dir: str,
    platform: str,
    frames: list[Path],
    model_config: ModelConfig,
    scoring_result: ScoringResult | None,
    error: str | None,
) -> None:
    """写入 trace 文件用于调试和审计。"""
    trace_path = Path(sample_dir) / f"aesthetics_trace_{platform}.json"

    trace = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rule_version": "1.0",
        "platform": platform,
        "selected_frames": [str(f) for f in frames],
        "frame_count": len(frames),
        "api_request": {
            "model": model_config.name,
            "image_count": len(frames),
            "token_input": scoring_result.usage.get("prompt_tokens", 0) if scoring_result else 0,
            "token_output": scoring_result.usage.get("completion_tokens", 0) if scoring_result else 0,
        },
        "parsed_result": asdict(scoring_result) if scoring_result else None,
        "error": error,
    }

    try:
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning("写入 trace 文件失败: %s", e)
