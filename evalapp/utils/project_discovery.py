"""Project root discovery utilities.

Provides platform-agnostic helpers for locating the actual project root
directory inside a generated output folder (e.g. ``generated_projects/{platform}/``).
Different generators may nest the real code one or more levels deep, so
these helpers search for known platform marker files.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

# Files whose presence indicates a valid generated project per platform.
PLATFORM_MARKERS: dict[str, list[str]] = {
    "android": [
        "build.gradle.kts",
        "build.gradle",
        "app/build.gradle.kts",
        "app/build.gradle",
        "settings.gradle.kts",
        "settings.gradle",
    ],
    "ios": [
        "*.xcodeproj",
        "*.xcworkspace",
        "Package.swift",
    ],
    "miniprogram": [
        "index.html",
        "app.json",
        "project.config.json",
    ],
    "expo_web": [
        "app.json",
        "package.json",
        "babel.config.js",
    ],
    "expo_android": [
        "app.json",
        "package.json",
        "babel.config.js",
    ],
    "expo_ios": [
        "app.json",
        "package.json",
        "babel.config.js",
    ],
    "h5": [
        "vite.config.ts",
        "vite.config.js",
        "vite.config.mts",
    ],
}


# Subdirectories never worth descending into during BFS project-root
# discovery (huge dependency trees / VCS internals / build outputs).
_SKIP_DIR_NAMES = frozenset({"node_modules", ".git", "dist", "build"})


def _package_json_has_script(pkg_path: Path, script_name: str) -> bool:
    """Return True if *pkg_path* exists and contains *script_name* in scripts.

    Robust against malformed files: unreadable/corrupt JSON, non-object
    top level, ``scripts`` being null or a non-dict (e.g. a string, where
    ``in`` would silently do substring matching) all yield False.
    """
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    scripts = data.get("scripts")
    return isinstance(scripts, dict) and script_name in scripts


def check_markers(directory: Path, platform: str) -> bool:
    """Return True if *directory* contains at least one expected marker.

    For expo_web platform, a ``build:web`` script in package.json is a
    POSITIVE requirement — not merely a veto when package.json exists.
    This prevents auxiliary directories (e.g. ``capability/`` with only a
    ``test`` script) or directories without any package.json from being
    mistakenly selected as the project root during BFS discovery: the
    real app root is the only directory that can actually run
    ``npm run build:web``.
    """
    # expo_web positive requirement (capability/ interference directory
    # case, 2026-09-17): no package.json, or package.json lacking a
    # build:web script → not the project root, regardless of other markers.
    if platform == "expo_web" and not _package_json_has_script(
        directory / "package.json", "build:web"
    ):
        return False
    markers = PLATFORM_MARKERS.get(platform, [])
    for marker in markers:
        if "*" in marker:
            if list(directory.glob(marker)):
                return True
        elif (directory / marker).exists():
            return True
    return False


def find_project_root(project_dir: Path, platform: str, max_depth: int = 3) -> Path | None:
    """Return the directory containing platform markers.

    First checks *project_dir* itself, then searches subdirectories
    up to *max_depth* levels deep (BFS, shallow matches win).
    """
    if check_markers(project_dir, platform):
        return project_dir
    if not project_dir.exists() or not project_dir.is_dir():
        return None

    queue = deque(
        (child, 1)
        for child in sorted(project_dir.iterdir())
        if child.is_dir()
        and not child.name.startswith(".")
        and child.name not in _SKIP_DIR_NAMES
    )

    while queue:
        current, depth = queue.popleft()
        if check_markers(current, platform):
            return current
        if depth < max_depth:
            for child in sorted(current.iterdir()):
                if (
                    child.is_dir()
                    and not child.name.startswith(".")
                    and child.name not in _SKIP_DIR_NAMES
                ):
                    queue.append((child, depth + 1))

    return None


def has_project_marker(project_dir: Path, platform: str) -> bool:
    """Return True if *project_dir* (or a descendant) has a marker."""
    if find_project_root(project_dir, platform) is not None:
        return True
    # Fallback: if we don't know the platform, check that the directory is
    # non-empty (at least a few files were generated).
    markers = PLATFORM_MARKERS.get(platform, [])
    if not markers:
        children = list(project_dir.iterdir()) if project_dir.exists() else []
        return len(children) >= 2
    return False
