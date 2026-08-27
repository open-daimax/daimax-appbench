"""Build phase: compile and package generated projects."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .state import _ANSI_ESCAPE_RE, best_effort_error, run_command
from ...utils.device import get_or_boot_android_emulator
from ...utils.logging import get_logger

logger = get_logger(__name__)

# Pattern to match CDN base URLs injected by H5 builds.
# When --skip-publish is used, assets are NOT uploaded to CDN so these
# URLs return 404.  We rewrite them to relative paths ("./") so that
# the local static server can serve the assets from disk.
#
# Old pattern (r"https?://[^\s\"']+/h5/dist/") assumed the URL path
# was always ``.../h5/dist/``, but the generator's H5 builds now embed a
# project ID segment, producing paths like ``.../h5/<projectID>/1/dist/``.
# The new pattern targets ``(src|href)="https://...any.../dist/"`` to
# cover both old and new CDN URL formats while avoiding false matches
# on non-asset URLs (e.g. vconsole's ``https://unpkg.com/.../dist/``
# which appears inside a JS string, not an HTML attribute).
_CDN_BASE_URL_RE = re.compile(
    r"((?:src|href)=[\"\'])https?://[^\s\"\']+/dist/"
)


def build_project(
    *,
    build_app_script: Path,
    project_path: str,
    platform: str,
    build_type: str,
    clean_build: bool,
    android_output_format: str,
    ios_output_format: str,
    build_timeout: int,
    stream_output: bool,
    device_id: str | None = None,
) -> dict[str, object]:
    """Build a generated project for the given platform.

    Returns dict with keys: success, message, artifact_path, duration_ms.
    """
    if not build_app_script.exists():
        return {
            "success": False,
            "message": f"build-app script not found at {build_app_script}",
            "artifact_path": "",
            "duration_ms": None,
        }

    # 提前校验项目源码目录，避免 subprocess 报 cwd 不存在的 FileNotFoundError
    # 被上游误读为 "Command not found"。常见于 Expo 跨端工作区被复用
    # 但目标平台代码尚未生成的场景。
    if not Path(project_path).is_dir():
        return {
            "success": False,
            "message": f"Project directory does not exist: {project_path}",
            "artifact_path": "",
            "duration_ms": None,
        }

    output_format = output_format_for(platform, android_output_format, ios_output_format)

    # ── 构建产物缓存检测：非 clean_build 模式下，若产物已存在则跳过构建 ──
    if not clean_build:
        cached_artifact = find_artifact(project_path, output_format)
        if cached_artifact and Path(cached_artifact).is_file():
            logger.info(
                "Build artifact already exists, skipping build: %s",
                cached_artifact,
            )
            return {
                "success": True,
                "message": "build skipped: artifact already exists",
                "artifact_path": cached_artifact,
                "duration_ms": 0,
            }

    cmd = [
        sys.executable,
        str(build_app_script),
        "--project-dir",
        project_path,
        "--platform",
        platform,
        "--build-type",
        build_type,
        "--output-format",
        output_format,
    ]
    if clean_build:
        cmd.append("--clean")

    # For Android, ensure an emulator is booted before building so that
    # ``npx expo run:android`` has a target device.
    if platform in ("android", "expo_android"):
        emu_id = get_or_boot_android_emulator()
        if emu_id:
            if platform != "expo_android":
                # Expo CLI auto-detects connected devices; passing --device-id
                # with adb serial format (emulator-5554) causes "Could not find
                # device with name" errors. Only pass for native android builds.
                cmd.extend(["--device-id", emu_id])
            # Set up adb reverse so Metro bundler is reachable from emulator
            # via localhost:8081 (critical for debug builds).
            try:
                import subprocess as _sp
                from evalapp.utils.paths import get_android_home
                import os as _os
                _adb = _os.path.join(get_android_home(), "platform-tools", "adb")
                _sp.run([_adb, "-s", emu_id, "reverse", "tcp:8081", "tcp:8081"],
                        capture_output=True, timeout=5)
            except Exception:
                pass

    # For iOS / expo_ios, pass the device UDID so that parallel builds
    # target different simulators instead of all hitting the default one.
    if platform in ("ios", "expo_ios") and device_id:
        cmd.extend(["--device-id", device_id])

    command_result = run_command(
        cmd,
        cwd=project_path,
        timeout=build_timeout,
        stream_output=stream_output,
        prefix="build",
    )
    metadata = parse_build_metadata(command_result.stdout)
    artifact_path = ""
    if metadata:
        artifact_path = str(
            metadata.get("apk_path")
            or metadata.get("app_path")
            or metadata.get("ipa_path")
            or ""
        )
    if not artifact_path:
        artifact_path = find_artifact(project_path, output_format)

    if command_result.returncode != 0:
        message = best_effort_error(command_result)
        return {
            "success": False,
            "message": message,
            "artifact_path": artifact_path,
            "duration_ms": command_result.duration_ms,
        }

    if not artifact_path:
        return {
            "success": False,
            "message": "build-app completed but no installable artifact was found",
            "artifact_path": "",
            "duration_ms": command_result.duration_ms,
        }

    return {
        "success": True,
        "message": "",
        "artifact_path": artifact_path,
        "duration_ms": command_result.duration_ms,
    }


def find_artifact(project_path: str, output_format: str) -> str:
    """Locate the built artifact in the project directory.

    [性能优化] 增加更多排除目录、限制搜索深度，减少 rglob 遍历的文件数。
    对于大型项目目录（含深层 node_modules）可减少 80%+ 的文件系统遍历。
    """
    project_root = Path(project_path)
    candidates: list[Path] = []

    # 扩展排除目录集合，避免进入大型依赖/缓存目录
    _EXCLUDED_DIRS = {
        "node_modules", ".git", ".idea", "Pods",
        ".gradle", "__pycache__", ".venv", ".cache",
        ".build", "dist-h5", "dist",
    }

    for path in project_root.rglob(f"*.{output_format}"):
        # 检查是否在排除目录中
        if _EXCLUDED_DIRS.intersection(path.parts):
            continue
        if output_format == "apk" and (
            "androidTest" in path.name or "androidTest" in str(path.parent)
        ):
            continue
        candidates.append(path)
        # 早期终止：找到在 build/outputs 目录下的工件即可返回
        if "build" in path.parts and "outputs" in path.parts:
            return str(path)

    if not candidates:
        return ""

    # Prefer Release over Debug, then prefer conventional build output dirs.
    candidates.sort(
        key=lambda p: (
            any("debug" in part.lower() for part in p.parts),
            "build" not in p.parts,
            "outputs" not in p.parts,
            str(p),
        )
    )
    return str(candidates[0])


def output_format_for(
    platform: str,
    android_output_format: str,
    ios_output_format: str,
) -> str:
    """Return the artifact file extension for the given platform."""
    if platform == "android" or platform == "expo_android":
        return android_output_format
    if platform == "ios" or platform == "expo_ios":
        return ios_output_format
    if platform == "miniprogram" or platform == "expo_web":
        # miniprogram / expo_web uses H5 build path; return "h5" as a defensive
        # fallback even though this function should not normally be
        # called for these platforms (they go through build_and_serve_h5).
        return "h5"
    raise ValueError(f"Unsupported platform: {platform}")


def parse_build_metadata(output: str) -> dict | None:
    """Parse build metadata JSON from build script output."""
    cleaned = _ANSI_ESCAPE_RE.sub("", output)
    decoder = json.JSONDecoder()
    candidate: dict | None = None
    for idx, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(cleaned[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "success" in parsed and "platform" in parsed:
            candidate = parsed
    return candidate


def rewrite_cdn_to_local(serve_root: Path) -> None:
    """Rewrite CDN asset URLs to relative paths in the H5 build output.

    The H5 build injects absolute CDN URLs for JS, CSS and chunk assets
    (e.g. ``https://...oss.../app_factory/.../<projectID>/1/dist/assets/app.js``).
    When the build runs with ``--skip-publish`` these remote resources don't
    exist (404), causing a blank page.

    This method rewrites all such URLs to ``./`` so that ``npx serve``
    can serve the local copies from disk.

    The regex captures ``(src|href)=".../dist/"`` and replaces only the
    URL portion, preserving the HTML attribute prefix.
    """
    pattern = _CDN_BASE_URL_RE
    targets = [serve_root / "index.html"]
    js_dir = serve_root / "js"
    if js_dir.is_dir():
        targets.extend(js_dir.glob("*.js"))

    for filepath in targets:
        if not filepath.is_file():
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
        except OSError:
            continue
        new_content = pattern.sub(r"\1./", content)
        if new_content != content:
            filepath.write_text(new_content, encoding="utf-8")
            logger.info(
                "Rewrote CDN URLs to relative paths in %s",
                filepath.name,
            )


def find_h5_serve_root(dist_h5: Path) -> Path | None:
    """Locate the directory containing index.html inside *dist_h5*.

    Many uni-app / miniprogram H5 builds place index.html in a
    sub-directory (e.g. ``dist-h5/build/h5/``).  We walk the tree
    (breadth-first, max 3 levels deep) and return the shallowest
    directory that contains an ``index.html``.  Returns *None* if
    no index.html is found anywhere.
    """
    # Check the root first
    if (dist_h5 / "index.html").is_file():
        return dist_h5

    # BFS up to 3 levels deep
    from collections import deque

    queue: deque[tuple[Path, int]] = deque()
    queue.append((dist_h5, 0))
    while queue:
        current, depth = queue.popleft()
        if depth > 3:
            continue
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if (child / "index.html").is_file():
                    return child
                if depth < 3:
                    queue.append((child, depth + 1))
    return None
