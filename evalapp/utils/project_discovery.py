"""Project root discovery utilities.

Provides platform-agnostic helpers for locating the actual project root
directory inside a generated output folder (e.g. ``generated_projects/{platform}/``).
Different generators may nest the real code one or more levels deep, so
these helpers search for known platform marker files.
"""

from __future__ import annotations

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


def check_markers(directory: Path, platform: str) -> bool:
    """Return True if *directory* contains at least one expected marker."""
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
        if child.is_dir() and not child.name.startswith(".")
    )

    while queue:
        current, depth = queue.popleft()
        if check_markers(current, platform):
            return current
        if depth < max_depth:
            for child in sorted(current.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
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
