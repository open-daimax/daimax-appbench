"""Device log collector for crash and ANR detection during E2E tests.

Monitors device logs (Android logcat / iOS os_log) in a background process
during test execution and parses the output for crash and ANR events.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import IO

from ..models import ANREvent, CrashEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Android logcat patterns
# ---------------------------------------------------------------------------

_ANDROID_CRASH_PATTERNS = [
    re.compile(r"FATAL EXCEPTION", re.IGNORECASE),
    re.compile(r"Process:\s*(\S+),\s*PID:\s*\d+"),
    re.compile(r"signal\s+\d+\s*\(SIG\w+\)", re.IGNORECASE),
    re.compile(r"java\.lang\.\w+Error", re.IGNORECASE),
    re.compile(r"java\.lang\.\w+Exception", re.IGNORECASE),
]

_ANDROID_ANR_PATTERNS = [
    re.compile(r"ANR\s+in\s+(\S+)", re.IGNORECASE),
    re.compile(r"Input\s+dispatching\s+timed\s+out", re.IGNORECASE),
    re.compile(r"Reason:\s+(.+)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# iOS log patterns
# ---------------------------------------------------------------------------

_IOS_CRASH_PATTERNS = [
    re.compile(r"(EXC_BAD_ACCESS|EXC_CRASH|SIGABRT|SIGSEGV|SIGBUS)", re.IGNORECASE),
    re.compile(r"Terminating app due to uncaught exception", re.IGNORECASE),
    re.compile(r"fatal error", re.IGNORECASE),
    re.compile(r"\*\*\* Terminating app", re.IGNORECASE),
]

_IOS_ANR_PATTERNS = [
    re.compile(r"watchdog timeout", re.IGNORECASE),
    re.compile(r"scene.*did not finish launching in time", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Log reader thread
# ---------------------------------------------------------------------------


class _LogReaderThread(threading.Thread):
    """Reads lines from a subprocess pipe and stores them in a buffer."""

    def __init__(self, pipe: IO[str]) -> None:
        super().__init__(daemon=True)
        self.pipe = pipe
        self.lines: list[str] = []

    def run(self) -> None:
        try:
            for line in self.pipe:
                self.lines.append(line)
        except (OSError, ValueError) as e:
            logger.debug("_LogReaderThread 读取管道失败: %s", e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class DeviceLogCollector:
    """Collects device logs during E2E test execution.

    Usage::

        collector = DeviceLogCollector()
        collector.start("android", package_name="com.example.app")
        # ... run E2E tests ...
        crashes, anrs = collector.stop()
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._reader: _LogReaderThread | None = None
        self._platform: str = ""
        self._package_name: str = ""
        self._device_id: str | None = None

    def start(self, platform: str, package_name: str | None = None, device_id: str | None = None) -> None:
        """Start collecting device logs in the background.

        Args:
            platform: ``"android"`` or ``"ios"``.
            package_name: Optional app package/bundle id for filtering.
            device_id: Optional device identifier (e.g. Android serial or iOS UDID).
        """
        self._platform = platform
        self._package_name = package_name or ""
        self._device_id = device_id

        try:
            if platform in ("android", "expo_android"):
                self._start_android()
            elif platform in ("ios", "expo_ios"):
                self._start_ios()
            else:
                logger.warning("Unsupported platform for log collection: %s", platform)
        except FileNotFoundError as exc:
            logger.warning("Cannot start log collection – tool not found: %s", exc)
        except Exception as exc:
            logger.warning("Failed to start log collection: %s", exc)

    def stop(self) -> tuple[list[CrashEvent], list[ANREvent]]:
        """Stop log collection and parse collected output.

        Returns:
            A tuple of (crash_events, anr_events).
        """
        if self._process is None:
            return [], []

        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            try:
                self._process.kill()
            except (OSError, ProcessLookupError) as e:
                logger.debug("强杀 device log 进程失败: %s", e)

        lines: list[str] = []
        if self._reader is not None:
            self._reader.join(timeout=3)
            lines = self._reader.lines

        self._process = None
        self._reader = None

        if self._platform == "android":
            return _parse_android_logs(lines, self._package_name)
        elif self._platform == "ios":
            return _parse_ios_logs(lines, self._package_name)
        return [], []

    def save_raw_logs(self, output_path: Path) -> bool:
        """Save raw device logs to file for later review.

        Args:
            output_path: Destination file path for raw logs

        Returns:
            True if logs were saved successfully
        """
        if self._reader is None or not self._reader.lines:
            logger.warning("No log lines available to save")
            return False

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 限制日志文件大小为10MB
            max_size = 10 * 1024 * 1024  # 10MB
            all_text = '\n'.join(self._reader.lines)
            
            if len(all_text.encode('utf-8')) > max_size:
                # 截断保留最后10MB
                logger.warning(
                    "Log size exceeds 10MB, truncating to last 10MB"
                )
                all_text = all_text.encode('utf-8')[-max_size:].decode('utf-8', errors='ignore')
                # 确保从完整行开始
                first_newline = all_text.find('\n')
                if first_newline > 0:
                    all_text = all_text[first_newline + 1:]
            
            output_path.write_text(all_text, encoding='utf-8')
            logger.info(
                "Saved %d log lines to %s (%.1fMB)",
                len(self._reader.lines),
                output_path,
                len(all_text.encode('utf-8')) / 1024 / 1024
            )
            return True
        except Exception as e:
            logger.warning("Failed to save raw logs: %s", e)
            return False

    # -- private helpers -----------------------------------------------------

    def _start_android(self) -> None:
        """Start ``adb logcat`` in background."""
        # Clear existing logs first
        cmd = ["adb"]
        if self._device_id:
            cmd.extend(["-s", self._device_id])
        cmd.extend(["logcat", "-c"])
        subprocess.run(cmd, capture_output=True, timeout=10)

        cmd = ["adb"]
        if self._device_id:
            cmd.extend(["-s", self._device_id])
        cmd.extend(["logcat", "-v", "threadtime"])
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._reader = _LogReaderThread(self._process.stdout)  # type: ignore[arg-type]
        self._reader.start()
        logger.info("Android logcat collection started (device=%s)", self._device_id or "default")

    def _start_ios(self) -> None:
        """Start ``xcrun simctl spawn log stream`` in background."""
        target = self._device_id or "booted"
        predicate = "eventMessage contains 'crash' OR eventMessage contains 'error' OR eventMessage contains 'fatal'"
        cmd = [
            "xcrun", "simctl", "spawn", target,
            "log", "stream",
            "--predicate", predicate,
            "--style", "compact",
        ]
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._reader = _LogReaderThread(self._process.stdout)  # type: ignore[arg-type]
        self._reader.start()
        logger.info("iOS log collection started (device=%s)", target)


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


def _parse_android_logs(
    lines: list[str],
    package_name: str,
) -> tuple[list[CrashEvent], list[ANREvent]]:
    """Parse Android logcat lines for crash and ANR events."""
    crashes: list[CrashEvent] = []
    anrs: list[ANREvent] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # --- Crash detection ---
        if "FATAL EXCEPTION" in line or "FATAL" in line.upper():
            crash = _extract_android_crash(lines, i, package_name)
            if crash is not None:
                crashes.append(crash)
                i += 1
                continue

        # Also catch native crashes via signal patterns
        for pattern in _ANDROID_CRASH_PATTERNS[2:]:
            if pattern.search(line):
                if not package_name or package_name in line:
                    crashes.append(CrashEvent(
                        timestamp=_extract_logcat_timestamp(line),
                        signal=pattern.pattern,
                        process=package_name,
                        message=line.strip()[:500],
                    ))
                break

        # --- ANR detection ---
        anr_match = re.search(r"ANR\s+in\s+(\S+)", line, re.IGNORECASE)
        if anr_match:
            process = anr_match.group(1)
            if not package_name or package_name in process:
                reason = ""
                # Look ahead for "Reason:" line
                for j in range(i + 1, min(i + 10, len(lines))):
                    reason_match = re.search(r"Reason:\s+(.+)", lines[j])
                    if reason_match:
                        reason = reason_match.group(1).strip()
                        break
                anrs.append(ANREvent(
                    timestamp=_extract_logcat_timestamp(line),
                    process=process,
                    reason=reason,
                    message=line.strip()[:500],
                ))

        if re.search(r"Input\s+dispatching\s+timed\s+out", line, re.IGNORECASE):
            if not package_name or package_name in line:
                anrs.append(ANREvent(
                    timestamp=_extract_logcat_timestamp(line),
                    process=package_name,
                    reason="Input dispatching timed out",
                    message=line.strip()[:500],
                ))

        i += 1

    return _deduplicate_crashes(crashes), _deduplicate_anrs(anrs)


def _extract_android_crash(
    lines: list[str],
    start: int,
    package_name: str,
) -> CrashEvent | None:
    """Extract a crash event from a FATAL EXCEPTION block in logcat."""
    line = lines[start]
    timestamp = _extract_logcat_timestamp(line)

    # Gather a few lines of context
    context_lines = [line.strip()]
    process = ""
    signal = ""

    for j in range(start + 1, min(start + 20, len(lines))):
        ctx = lines[j].strip()
        context_lines.append(ctx)

        proc_match = re.search(r"Process:\s*(\S+)", ctx)
        if proc_match:
            process = proc_match.group(1).rstrip(",")

        sig_match = re.search(r"signal\s+\d+\s*\((SIG\w+)\)", ctx, re.IGNORECASE)
        if sig_match:
            signal = sig_match.group(1)

        # Stop at next log entry (timestamp at start)
        if j > start + 1 and re.match(r"\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", ctx):
            if "FATAL" not in ctx:
                break

    # Filter by package if specified
    if package_name and process and package_name not in process:
        return None

    return CrashEvent(
        timestamp=timestamp,
        signal=signal,
        process=process or package_name,
        message="\n".join(context_lines[:10])[:1000],
    )


def _extract_logcat_timestamp(line: str) -> str:
    """Extract timestamp from a logcat threadtime-format line."""
    match = re.match(r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)", line)
    return match.group(1) if match else ""


def _parse_ios_logs(
    lines: list[str],
    package_name: str,
) -> tuple[list[CrashEvent], list[ANREvent]]:
    """Parse iOS log stream output for crash and ANR events."""
    crashes: list[CrashEvent] = []
    anrs: list[ANREvent] = []

    for line in lines:
        # --- Crash detection ---
        for pattern in _IOS_CRASH_PATTERNS:
            match = pattern.search(line)
            if match:
                if not package_name or package_name in line:
                    crashes.append(CrashEvent(
                        timestamp=_extract_ios_timestamp(line),
                        signal=match.group(0),
                        process=package_name,
                        message=line.strip()[:500],
                    ))
                break

        # --- ANR detection ---
        for pattern in _IOS_ANR_PATTERNS:
            if pattern.search(line):
                if not package_name or package_name in line:
                    anrs.append(ANREvent(
                        timestamp=_extract_ios_timestamp(line),
                        process=package_name,
                        reason=pattern.pattern,
                        message=line.strip()[:500],
                    ))
                break

    return _deduplicate_crashes(crashes), _deduplicate_anrs(anrs)


def _extract_ios_timestamp(line: str) -> str:
    """Extract timestamp from an iOS log stream line."""
    match = re.match(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[\.\d]*)", line)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------


def _deduplicate_crashes(events: list[CrashEvent]) -> list[CrashEvent]:
    """Remove duplicate crash events (same message within short window)."""
    if len(events) <= 1:
        return events
    seen: set[str] = set()
    deduped: list[CrashEvent] = []
    for e in events:
        key = (e.process, e.signal, e.message[:100])
        key_str = str(key)
        if key_str not in seen:
            seen.add(key_str)
            deduped.append(e)
    return deduped


def _deduplicate_anrs(events: list[ANREvent]) -> list[ANREvent]:
    """Remove duplicate ANR events."""
    if len(events) <= 1:
        return events
    seen: set[str] = set()
    deduped: list[ANREvent] = []
    for e in events:
        key = (e.process, e.reason, e.message[:100])
        key_str = str(key)
        if key_str not in seen:
            seen.add(key_str)
            deduped.append(e)
    return deduped
