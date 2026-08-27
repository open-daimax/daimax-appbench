from .logging import setup_logging, get_logger
from .paths import get_project_root, get_test_cases_dir, get_results_dir, get_android_home, get_adb_path
from .process import run_command, run_command_async, run_streaming, Result, StreamingResult
from .files import extract_package_name, extract_ios_bundle_id, parse_ai_ui_test_output
from .device import (
    can_compile_successfully,
    run_e2e_tests,
    get_or_boot_ios_simulator,
    get_available_avd,
    start_and_wait_for_emulator,
    EmulatorStartupTimeoutError,
    EmulatorFailedToStartError,
    EmulatorHeartbeat,
)
from .project_discovery import (
    PLATFORM_MARKERS,
    check_markers,
    find_project_root,
    has_project_marker,
)
from .npm_registry import ensure_npm_registry_reachable

__all__ = [
    # logging
    "setup_logging", "get_logger",
    # paths
    "get_project_root", "get_test_cases_dir", "get_results_dir",
    "get_android_home", "get_adb_path",
    # process
    "run_command", "run_command_async", "run_streaming", "Result", "StreamingResult",
    # files
    "extract_package_name", "extract_ios_bundle_id", "parse_ai_ui_test_output",
    # device
    "can_compile_successfully", "run_e2e_tests",
    "get_or_boot_ios_simulator", "get_available_avd", "start_and_wait_for_emulator",
    "EmulatorStartupTimeoutError", "EmulatorFailedToStartError", "EmulatorHeartbeat",
    # project_discovery
    "PLATFORM_MARKERS", "check_markers", "find_project_root", "has_project_marker",
    # npm_registry
    "ensure_npm_registry_reachable",
]
