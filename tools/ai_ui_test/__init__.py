"""AI UI Test 工具 Python 入口与外部服务守卫。

本模块提供 ai-ui-test 工具的 Python 侧入口，以及可选外部模型服务增强能力的
配置守卫。所有外部服务相关调用必须先通过 :func:`require_external_service` 检查。
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# 外部模型服务配置守卫
# ---------------------------------------------------------------------------

def get_external_service_config() -> "ExternalServiceConfig":
    """延迟导入，避免循环依赖。"""
    from evalapp.config import get_config
    return get_config().external_service


def is_external_service_enabled() -> bool:
    """检查外部模型服务是否已启用且 API Key 有效。"""
    cfg = get_external_service_config()
    if not cfg.enabled:
        return False
    if not cfg.effective_api_key:
        logger.warning(
            "[external-service] enabled=true but api_key is empty; "
            "falling back to built-in tools"
        )
        return False
    return True


def require_external_service(feature_name: str = "") -> Callable[[F], F]:
    """装饰器：确保外部模型服务已启用后才执行被装饰函数。

    未启用时自动回退并返回 ``None``，调用方应判断返回值并降级处理。

    用法::

        @require_external_service("enhanced_visual_analysis")
        def analyze_with_external_service(screenshot_path: str) -> dict:
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_external_service_enabled():
                logger.info(
                    "[external-service] %s skipped: service not enabled or "
                    "api_key missing, falling back to built-in tools",
                    feature_name or func.__name__,
                )
                return None
            return func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# 工具入口辅助
# ---------------------------------------------------------------------------

def resolve_tool_script_dir() -> str:
    """返回内置 ai-ui-test Node.js 工具的目录路径。"""
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent / "ai-ui-test")
