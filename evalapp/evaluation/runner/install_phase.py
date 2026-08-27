"""Install phase: deploy apps to devices/simulators."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .state import run_command, best_effort_error
from .build_phase import find_artifact
from ...utils.device import get_or_boot_ios_simulator, get_or_boot_android_emulator
from ...utils.files import extract_ios_bundle_id
from ...utils.logging import get_logger

logger = get_logger(__name__)


def install_artifact(
    *,
    install_app_script: Path,
    platform: str,
    artifact_path: str,
    install_device_id: str | None,
    install_auto_install: bool,
    install_timeout: int,
    stream_output: bool,
) -> dict[str, object]:
    """Install an app artifact on the target platform.

    Returns dict with keys: success, message.
    """
    if not install_app_script.exists():
        return {
            "success": False,
            "message": f"install-app script not found at {install_app_script}",
        }
    if not artifact_path or not Path(artifact_path).exists():
        return {
            "success": False,
            "message": f"artifact not found: {artifact_path}",
        }

    cmd = [
        sys.executable,
        str(install_app_script),
        "--platform",
        platform,
        "--app-path",
        artifact_path,
    ]
    # For iOS, ensure a preferred simulator is booted in-project before
    # delegating to the install-app skill. This keeps the device-selection
    # policy (Pro Max > Pro > regular > SE; newer model numbers first)
    # under this repo's control instead of the global skill.
    device_id = install_device_id
    if platform in ("ios", "expo_ios") and not device_id:
        udid = get_or_boot_ios_simulator()
        if udid:
            device_id = udid
    elif platform in ("android", "expo_android") and not device_id:
        emu_id = get_or_boot_android_emulator()
        if emu_id:
            device_id = emu_id
    if device_id:
        cmd.extend(["--device-id", device_id])
    if install_auto_install:
        cmd.append("--auto-install")

    command_result = run_command(
        cmd,
        cwd=str(install_app_script.parent),
        timeout=install_timeout,
        stream_output=stream_output,
        prefix="install",
    )
    if command_result.returncode != 0:
        return {
            "success": False,
            "message": best_effort_error(command_result),
        }

    return {
        "success": True,
        "message": "",
    }


def uninstall_app(
    platform: str,
    package_name: str,
    device_id: str | None = None,
) -> dict[str, object]:
    """Uninstall an app after evaluation.

    Args:
        platform: Target platform (android/ios).
        package_name: App package name (Android package name or iOS bundle ID).
        device_id: Device ID (optional).

    Returns:
        {"success": bool, "message": str}
    """
    if not package_name:
        return {"success": False, "message": "package_name is empty, skip uninstall"}

    if platform in ("ios", "expo_ios"):
        cmd = ["xcrun", "simctl", "uninstall", device_id or "booted", package_name]
    elif platform in ("android", "expo_android"):
        cmd = ["adb"]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["uninstall", package_name])
    else:
        return {"success": True, "message": f"platform '{platform}' does not require uninstall"}

    try:
        logger.info("Uninstalling app: %s (platform=%s)", package_name, platform)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            logger.warning("App uninstall failed (non-fatal): %s", stderr)
            return {"success": False, "message": stderr}
        logger.info("App uninstalled successfully: %s", package_name)
        return {"success": True, "message": ""}
    except subprocess.TimeoutExpired:
        logger.warning("App uninstall timed out (non-fatal): %s", package_name)
        return {"success": False, "message": "uninstall timed out"}
    except Exception as e:
        logger.warning("App uninstall error (non-fatal): %s", e)
        return {"success": False, "message": str(e)}


def resolve_package_name(
    platform: str,
    project_path: str,
    artifact_path: str,
) -> str | None:
    """Resolve the package name for the given platform and artifact."""
    if platform in ("android", "expo_android"):
        return extract_android_package_name(project_path)
    if platform in ("ios", "expo_ios"):
        # Try app.json first (Expo project convention)
        bundle_id = extract_ios_bundle_id_from_app_json(project_path)
        if bundle_id:
            return bundle_id
        if artifact_path.endswith(".app"):
            return extract_ios_bundle_id(artifact_path)
        app_bundle = find_artifact(project_path, "app")
        if app_bundle:
            return extract_ios_bundle_id(app_bundle)
    return None


def extract_ios_bundle_id_from_app_json(project_path: str) -> str | None:
    """Extract the iOS bundle identifier from Expo app.json."""
    project_root = Path(project_path)
    app_json = project_root / "app.json"
    if not app_json.exists():
        return None
    try:
        data = json.loads(app_json.read_text())
        expo_cfg = data.get("expo", data)
        bundle_id = (expo_cfg.get("ios") or {}).get("bundleIdentifier", "").strip()
        if bundle_id:
            return bundle_id
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("读取 app.json 失败 (%s): %s", app_json, e)
    return None


def extract_android_package_name(project_path: str) -> str | None:
    """Extract the Android package name from project files."""
    project_root = Path(project_path)

    # 1. app_config.json (生成器项目约定)
    app_config = project_root / "app_config.json"
    if app_config.exists():
        try:
            data = json.loads(app_config.read_text())
            pkg = data.get("applicationId", "").strip()
            if pkg:
                return pkg
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("读取 app_config.json 失败 (%s): %s", app_config, e)

    # 2. Expo app.json → expo.android.package
    app_json = project_root / "app.json"
    if app_json.exists():
        try:
            data = json.loads(app_json.read_text())
            expo_cfg = data.get("expo", data)
            pkg = (expo_cfg.get("android") or {}).get("package", "").strip()
            if pkg:
                return pkg
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("读取 app.json 失败 (%s): %s", app_json, e)

    # 3. gradle 字面量 applicationId = "..."
    for gradle_file in ("app/build.gradle.kts", "app/build.gradle",
                        # Expo prebuild: android/ subdirectory
                        "android/app/build.gradle.kts", "android/app/build.gradle"):
        path = project_root / gradle_file
        if not path.exists():
            continue
        content = path.read_text()
        match = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    return None
