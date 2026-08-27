"""Device and emulator management utilities for EvalApp.

Migrated from ``utils/helpers.py`` — functions for Android emulator
management, iOS simulator booting, build checking, and E2E test execution.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, List

from .logging import get_logger
from .paths import get_android_home, get_adb_path
from .process import run_command, run_command_async

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Build checking
# ---------------------------------------------------------------------------


def can_compile_successfully(
    build_commands: List[str],
    project_dir: str,
    timeout: int | None = None,
) -> bool:
    """Checks if a project can compile successfully."""
    for build_command in build_commands:
        result = run_command(build_command, cwd=project_dir, timeout=timeout)
        logging.info(f"build stdout: {result.stdout}")
        logging.info(f"build stderr: {result.stderr}")
        if result.exit_code != 0:
            return False
    return True


# ---------------------------------------------------------------------------
# E2E test execution
# ---------------------------------------------------------------------------


def run_e2e_tests(
    project_dir: str,
    test_cases_file: str | None,
    platform: str,
    package_name: str | None = None,
    ai_ui_test_dir: str | None = None,
    timeout: int = 300,
) -> dict:
    """Run E2E UI tests using ai-ui-test.

    Args:
        project_dir: Path to the generated project directory.
        test_cases_file: Path to test cases JSON file.
        platform: Target platform (android/ios).
        package_name: App package name for Android.
        ai_ui_test_dir: Path to ai-ui-test scripts directory.
        timeout: Per-test timeout in seconds.

    Returns:
        Dict with 'passed', 'failed', 'total', 'results' keys.
    """
    from .files import parse_ai_ui_test_output

    if ai_ui_test_dir is None:
        # 使用仓库内置的 ai-ui-test（tools/ai-ui-test），不再依赖 ~/.agents/skills 下载安装
        from .paths import get_project_root
        ai_ui_test_dir = str(get_project_root() / "tools" / "ai-ui-test")

    # Prefer new entry point (dist/command/ai-ui-test.js) over legacy (dist/index.js)
    new_entry = Path(ai_ui_test_dir) / "dist" / "command" / "ai-ui-test.js"
    index_js = new_entry if new_entry.exists() else Path(ai_ui_test_dir) / "dist" / "index.js"
    if not index_js.exists():
        logger.error(f"ai-ui-test not found at {index_js}")
        return {"passed": 0, "failed": 0, "total": 0, "results": [], "error": "ai-ui-test not found"}

    # Load test cases (supports both plain array and wrapped {"test_cases": [...]} format)
    test_cases = []
    if test_cases_file and Path(test_cases_file).exists():
        with open(test_cases_file, "r") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            test_cases = raw
        elif isinstance(raw, dict):
            test_cases = raw.get("test_cases", [])

    if not test_cases:
        logger.warning("No test cases to execute")
        return {"passed": 0, "failed": 0, "total": 0, "results": []}

    results = []
    passed = 0
    failed = 0
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    for tc in test_cases:
        tc_id = tc.get("id", tc.get("test_case_id", "unknown"))
        steps = tc.get("steps", [])
        expected = tc.get("expected_result", tc.get("description", ""))

        # Build steps text
        if isinstance(steps, list):
            actions = []
            for step in steps:
                if isinstance(step, str):
                    action = step.split(" -> 预期:")[0].strip()
                    actions.append(action)
                elif isinstance(step, dict):
                    actions.append(step.get("action", str(step)))
            steps_text = "，".join(actions) if actions else str(tc.get("description", ""))
        else:
            steps_text = str(steps)

        cmd = [
            "node",
            str(index_js),
            steps_text,
            expected,
            "--platform", platform,
            "--case-id", str(tc_id),
        ]
        if package_name:
            cmd.extend(["--package", package_name])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=ai_ui_test_dir,
                env=env,
            )

            stdout = proc.stdout or ""
            # Parse JSON result
            result = parse_ai_ui_test_output(stdout)
            if result is not None:
                tc_passed = result.get("success", False)
            else:
                tc_passed = proc.returncode == 0

            if tc_passed:
                passed += 1
            else:
                failed += 1

            if result:
                detail_text = result.get("reason") or result.get("error", "")
                if not tc_passed and result.get("errorType"):
                    detail_text = f"[{result['errorType']}] {detail_text}"
            else:
                detail_text = stdout[-500:] if stdout else ""

            results.append({
                "test_case_id": tc_id,
                "passed": tc_passed,
                "details": detail_text,
            })

        except subprocess.TimeoutExpired:
            failed += 1
            results.append({
                "test_case_id": tc_id,
                "passed": False,
                "details": f"Timed out after {timeout}s",
            })
        except Exception as e:
            failed += 1
            results.append({
                "test_case_id": tc_id,
                "passed": False,
                "details": f"Error: {e}",
            })

    return {
        "passed": passed,
        "failed": failed,
        "total": len(test_cases),
        "results": results,
    }


# ---------------------------------------------------------------------------
# iOS Simulator
# ---------------------------------------------------------------------------


def _ios_simulator_priority(name: str) -> tuple[int, int, str]:
    """Sort key for choosing the preferred iPhone simulator.

    Order:
      1) Category: Pro Max > Pro > regular > SE
      2) Within same category, prefer newer model number (e.g. 17 > 16 > 15)
      3) Fallback to name for stable ordering
    """
    m = re.search(r"iPhone\s+(\d+)", name)
    version = int(m.group(1)) if m else 0
    if "Pro Max" in name:
        category = 0
    elif "Pro" in name:
        category = 1
    elif "SE" in name:
        category = 3
    else:
        category = 2
    return (category, -version, name)


def get_or_boot_ios_simulator() -> str | None:
    """Get a booted iOS simulator UDID, or boot one if none is running.

    Selection preference: Pro Max > Pro > regular > SE; within the same
    category prefer newer model numbers (e.g. iPhone 17 Pro Max over
    iPhone 15 Pro Max).

    Returns the UDID of a booted iPhone simulator, or None if unavailable.
    """
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "available", "-j"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        devices = data.get("devices", {})

        # 1) If any iPhone simulator is already booted, return the
        #    highest-priority one among them.
        booted: list[tuple[str, str]] = []
        for _runtime, device_list in devices.items():
            for device in device_list:
                name = device.get("name", "")
                if device.get("state") == "Booted" and "iPhone" in name:
                    booted.append((name, device["udid"]))
        if booted:
            booted.sort(key=lambda it: _ios_simulator_priority(it[0]))
            chosen_name, chosen_udid = booted[0]
            logger.info(f"Found booted simulator: {chosen_name} ({chosen_udid})")
            return chosen_udid

        # 2) No booted simulator — collect candidates across iOS runtimes,
        #    sort by preference, and boot the best one.
        candidates: list[tuple[str, str]] = []
        for runtime, device_list in devices.items():
            if "iOS" not in runtime:
                continue
            for device in device_list:
                name = device.get("name", "")
                if "iPhone" in name and device.get("isAvailable", False):
                    candidates.append((name, device["udid"]))

        candidates.sort(key=lambda it: _ios_simulator_priority(it[0]))

        for name, udid in candidates:
            logger.info(f"Booting simulator: {name} ({udid})")
            boot_result = subprocess.run(
                ["xcrun", "simctl", "boot", udid],
                capture_output=True, text=True, timeout=60,
            )
            if boot_result.returncode == 0:
                logger.info(f"Simulator booted: {name}")
                return udid
            logger.warning(f"Failed to boot {name}: {boot_result.stderr.strip()}")
    except Exception as e:
        logger.error(f"Error getting iOS simulator: {e}")
    return None


# ---------------------------------------------------------------------------
# Android Emulator
# ---------------------------------------------------------------------------


class EmulatorStartupTimeoutError(Exception):
    """Raised when the emulator fails to start within the timeout period."""

    timeout_seconds: int

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds


class EmulatorFailedToStartError(Exception):
    """Raised when the emulator fails to start for any reason other than timeout."""
    pass


class EmulatorHeartbeat(threading.Thread):
    """A thread that monitors the status of an Android emulator."""

    def __init__(
        self,
        emulator_process: subprocess.Popen,
        adb_path: str,
        log_file: str,
        interval_seconds: int = 15,
    ) -> None:
        super().__init__()
        self.emulator_process = emulator_process
        self.adb_path = adb_path
        self.log_file = log_file
        self.interval_seconds = interval_seconds
        self.daemon = True
        self._stop_event = threading.Event()
        self.failure: str | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            if self.emulator_process.poll() is not None:
                message = f"CRITICAL: Emulator process (PID {self.emulator_process.pid}) has exited unexpectedly."
                logger.error(message)
                self.failure = message
                os.kill(os.getpid(), signal.SIGINT)
                break

            try:
                result = subprocess.run(
                    [self.adb_path, "devices"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if "emulator" not in result.stdout.lower():
                    message = "CRITICAL: Emulator went offline."
                    logger.error(message)
                    self.failure = message
                    os.kill(os.getpid(), signal.SIGINT)
                    break
            except subprocess.TimeoutExpired:
                logger.warning("ADB devices command timed out.")
            except Exception as e:
                logger.warning(f"Error checking emulator status: {e}")

            self._stop_event.wait(self.interval_seconds)


def get_available_avd() -> str | None:
    """Get the first available AVD name from the emulator."""
    emulator_path = os.path.join(get_android_home(), "emulator", "emulator")
    try:
        result = subprocess.run(
            [emulator_path, "-list-avds"],
            capture_output=True, text=True, timeout=10,
        )
        avds = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return avds[0] if avds else None
    except Exception:
        return None


def start_and_wait_for_emulator(
    log_file: str, emulator_avd_name: str, timeout_seconds: int = 180
) -> subprocess.Popen[Any]:
    """Starts an Android emulator and waits for it to be fully booted.

    Args:
        log_file: Path to log file.
        emulator_avd_name: The name of the AVD to start.
        timeout_seconds: Maximum time to wait for boot.

    Returns:
        A subprocess.Popen for the emulator process.

    Raises:
        EmulatorStartupTimeoutError: If emulator doesn't boot in time.
        EmulatorFailedToStartError: If emulator fails to start.
    """
    emulator_path = os.path.join(get_android_home(), "emulator", "emulator")
    emulator_command = (
        f"{emulator_path} -avd {emulator_avd_name} -no-snapshot -no-window -no-audio"
    )
    check_boot_command = f"{get_adb_path()} shell getprop sys.boot_completed"

    logger.info(f"Starting emulator: {emulator_command}")
    start_time = time.time()
    try:
        emulator_process = run_command_async(emulator_command)
        time.sleep(5)

        logger.info("Waiting for emulator to boot...")
        while time.time() - start_time < timeout_seconds:
            result = run_command(check_boot_command)
            if "1" in result.stdout.strip():
                logger.info("Emulator fully booted and ready!")
                break
            time.sleep(5)
        else:
            logger.error("Emulator did not boot within the timeout period.")
            raise EmulatorStartupTimeoutError(timeout_seconds)
    except EmulatorStartupTimeoutError:
        raise
    except Exception as e:
        logger.error(f"Error during emulator startup: {e}")
        raise EmulatorFailedToStartError()

    return emulator_process


def _select_best_avd(avds: list[str]) -> str:
    """Select the best AVD from a list.

    Preference:
      1. AVDs whose name contains "Pixel" (case-insensitive), sorted by
         API level descending.
      2. Any other AVD, sorted by API level descending.
    """
    pixel_avds = [a for a in avds if "pixel" in a.lower()]
    if pixel_avds:

        def _pixel_key(name: str) -> tuple:
            m = re.search(r"API[_\s]?(\d+)", name, re.I)
            api = int(m.group(1)) if m else 0
            return (-api, name)

        pixel_avds.sort(key=_pixel_key)
        return pixel_avds[0]

    def _api_key(name: str) -> tuple:
        m = re.search(r"API[_\s]?(\d+)", name, re.I)
        api = int(m.group(1)) if m else 0
        return (-api, name)

    avds_copy = list(avds)
    avds_copy.sort(key=_api_key)
    return avds_copy[0]


def get_or_boot_android_emulator() -> str | None:
    """Get a running Android emulator device ID, or boot one if none is running.

    Checks ``adb devices`` for already-running emulators (device names
    starting with ``emulator-``).  If none are found, lists available AVDs
    via ``emulator -list-avds``, picks the best one (Pixel preferred, then
    highest API level), starts it, and waits for boot completion.

    Returns:
        The device ID (e.g. ``emulator-5554``) or *None* if the Android
        SDK is not available or no emulator can be started.
    """
    # 1) Locate adb
    try:
        adb = get_adb_path()
    except EnvironmentError as e:
        logger.warning("Android SDK not available: %s", e)
        return None

    # 2) Check for already-connected devices (physical device preferred over emulator)
    try:
        result = subprocess.run(
            [adb, "devices"],
            capture_output=True, text=True, timeout=10,
        )
        physical_devices = []
        emulators = []
        for line in result.stdout.strip().splitlines():
            if "\tdevice" not in line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                if parts[0].startswith("emulator-"):
                    emulators.append(parts[0])
                else:
                    physical_devices.append(parts[0])
        # 优先使用物理设备
        if physical_devices:
            device_id = physical_devices[0]
            logger.info("Found physical Android device: %s (preferred over emulator)", device_id)
            return device_id
        if emulators:
            device_id = emulators[0]
            logger.info("Found running Android emulator: %s", device_id)
            return device_id
    except Exception as e:
        logger.warning("Failed to check adb devices: %s", e)

    # 3) No running emulator — find an AVD to start
    try:
        android_home = get_android_home()
    except EnvironmentError as e:
        logger.warning("ANDROID_HOME not set: %s", e)
        return None

    emulator_path = os.path.join(android_home, "emulator", "emulator")
    if not os.path.exists(emulator_path):
        logger.warning("Emulator binary not found at %s", emulator_path)
        return None

    try:
        result = subprocess.run(
            [emulator_path, "-list-avds"],
            capture_output=True, text=True, timeout=10,
        )
        avds = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except Exception as e:
        logger.warning("Failed to list AVDs: %s", e)
        return None

    if not avds:
        logger.warning("No Android AVDs found")
        return None

    # 4) Select best AVD
    chosen_avd = _select_best_avd(avds)
    logger.info("Starting Android emulator with AVD: %s", chosen_avd)

    # 5) Start emulator (keep GUI visible for UI testing, no -no-window)
    try:
        subprocess.Popen(
            [emulator_path, "-avd", chosen_avd, "-no-snapshot", "-no-audio"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("Failed to start emulator: %s", e)
        return None

    # 6) Wait for boot completion
    logger.info("Waiting for emulator to boot...")
    start_time = time.time()
    boot_timeout = 180
    try:
        # Wait for adb to see the device
        subprocess.run(
            [adb, "wait-for-device"],
            capture_output=True, timeout=boot_timeout,
        )

        # Wait for boot_completed property
        while time.time() - start_time < boot_timeout:
            result = subprocess.run(
                [adb, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip() == "1":
                # Find the device ID
                devices_result = subprocess.run(
                    [adb, "devices"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in devices_result.stdout.strip().splitlines():
                    if line.startswith("emulator-"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "device":
                            device_id = parts[0]
                            logger.info("Android emulator booted: %s", device_id)
                            # Wait for PackageManager to be ready
                            pm_deadline = time.time() + 60
                            while time.time() < pm_deadline:
                                try:
                                    pm_result = subprocess.run(
                                        [adb, "-s", device_id, "shell", "pm", "list", "packages"],
                                        capture_output=True, text=True, timeout=10,
                                    )
                                    if pm_result.returncode == 0 and pm_result.stdout.strip():
                                        logger.info("%s PackageManager ready", device_id)
                                        break
                                except (subprocess.TimeoutExpired, OSError):
                                    pass
                                time.sleep(2)
                            else:
                                logger.warning("%s PackageManager not ready after 60s", device_id)
                            return device_id
                time.sleep(2)
            else:
                time.sleep(3)
        logger.warning(
            "Android emulator boot timed out after %s seconds", boot_timeout
        )
    except Exception as e:
        logger.warning("Error waiting for emulator boot: %s", e)

    return None
