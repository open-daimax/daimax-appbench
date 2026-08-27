"""File content parsing utilities for EvalApp.

Migrated from ``utils/helpers.py`` — functions that extract structured
information from project files (Gradle builds, iOS plists, etc.).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def extract_package_name(project_dir: str) -> str | None:
    """Extract Android applicationId from build.gradle(.kts).

    Searches for applicationId in build.gradle.kts or build.gradle files.
    """
    project_path = Path(project_dir)
    for gradle_file in ["app/build.gradle.kts", "app/build.gradle"]:
        gradle_path = project_path / gradle_file
        if gradle_path.exists():
            content = gradle_path.read_text()
            # Match applicationId "com.example.app" or applicationId = "com.example.app"
            match = re.search(
                r'applicationId\s*[=]?\s*"([^"]+)"', content
            )
            if match:
                return match.group(1)
    return None


def extract_ios_bundle_id(app_path: str) -> str | None:
    """Extract CFBundleIdentifier from an iOS .app bundle's Info.plist."""
    info_plist = Path(app_path) / "Info.plist"
    if not info_plist.exists():
        return None
    try:
        result = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleIdentifier", str(info_plist)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.error(f"Error extracting bundle ID: {e}")
    return None


def round_scores(data, ndigits=1):
    """递归地将 dict/list 中所有 float 值 round 到指定位数。

    仅处理 float 类型，int / str / bool 等不受影响。
    用于确保评分等数值字段统一保留1位小数。

    [性能优化]
    - 使用 ``type(data) is X`` 替代 ``isinstance``，避免 MRO 查找开销
      （外层 dict 使用 isinstance 以兼容 OrderedDict 等子类）。
    - 本地绑定 ``round`` 函数，避免重复查找全局符号。
    - bool 是 int 子类，但不是 float 子类，不需额外判断。
    """
    _round = round
    t = type(data)
    if t is float:
        return _round(data, ndigits)
    if t is dict or isinstance(data, dict):
        out = {}
        for k, v in data.items():
            vt = type(v)
            if vt is float:
                out[k] = _round(v, ndigits)
            elif vt is dict or vt is list or isinstance(v, (dict, list)):
                out[k] = round_scores(v, ndigits)
            else:
                out[k] = v
        return out
    if t is list or isinstance(data, list):
        out_list = []
        for item in data:
            it = type(item)
            if it is float:
                out_list.append(_round(item, ndigits))
            elif it is dict or it is list or isinstance(item, (dict, list)):
                out_list.append(round_scores(item, ndigits))
            else:
                out_list.append(item)
        return out_list
    return data


def parse_ai_ui_test_output(output: str) -> dict | None:
    """Parse the JSON result from ai-ui-test CLI output.

    Formerly ``_parse_ai_ui_test_output`` (private) in helpers.py;
    promoted to public as it is now in a dedicated module.
    """
    for line in output.split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            if "success" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None
