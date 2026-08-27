"""Path utility functions for EvalApp."""

from __future__ import annotations

import os
from pathlib import Path

# Project root is the EvalApp directory
_PROJECT_ROOT: Path | None = None


def get_project_root() -> Path:
    """Return the EvalApp project root directory."""
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    # Walk up from this file to find the EvalApp root
    # (evalapp/utils/paths.py -> evalapp/utils -> evalapp -> EvalApp)
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    return _PROJECT_ROOT


def set_project_root(path: Path) -> None:
    """Override the project root (useful for testing)."""
    global _PROJECT_ROOT
    _PROJECT_ROOT = path


def get_test_cases_dir() -> Path:
    """Return the default test_cases directory."""
    return get_project_root() / "test_cases"


def get_results_dir() -> Path:
    """已弃用：数据源统一为 workspace，此函数仅保留向后兼容。"""
    return get_project_root() / "results"


# ---------------------------------------------------------------------------
# Android / iOS SDK paths (migrated from utils/helpers.py)
# ---------------------------------------------------------------------------


def get_android_home() -> str:
    """Returns the Android SDK path from environment or common locations."""
    # Check environment variables
    for env_var in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
        path = os.environ.get(env_var)
        if path and os.path.exists(path):
            return path

    # Check common default paths
    for default_path in [
        os.path.expanduser("~/Library/Android/sdk"),  # macOS default
        os.path.expanduser("~/Android/Sdk"),           # Linux default
    ]:
        if os.path.exists(default_path):
            return default_path

    raise EnvironmentError(
        "Android SDK not found. Set ANDROID_HOME or ANDROID_SDK_ROOT"
        " environment variable, or install SDK to ~/Library/Android/sdk."
    )


def get_adb_path() -> str:
    """Returns the path to the adb executable."""
    return os.path.join(get_android_home(), "platform-tools", "adb")
