"""Device pool management for parallel evaluation.

Provides a thread-safe pool of Android emulators or iOS simulators
that can be acquired / released by concurrent workers.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Dict, List, Set

from .device import _ios_simulator_priority
from .logging import get_logger
from .paths import get_adb_path, get_android_home
from .process import run_command_async

logger = get_logger(__name__)

# Global hard limit — also serves as the default upper bound.
MAX_DEVICES_LIMIT = 10

# Android emulator base port — each instance occupies two consecutive ports.
_ANDROID_BASE_PORT = 5554


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DeviceSlot:
    """Represents a single device allocated from the pool."""

    device_id: str  # emulator-{port} for Android; UDID for iOS
    platform: str  # "android" or "ios"
    port: int | None = None  # Console port (Android only)


# ---------------------------------------------------------------------------
# DevicePool
# ---------------------------------------------------------------------------


@dataclass
class _DeviceInventory:
    """Private initialization or detached cleanup state, owned by one lifecycle call."""

    available: list[DeviceSlot] = field(default_factory=list)
    android_processes: dict[int, subprocess.Popen] = field(default_factory=dict)
    ios_booted: set[str] = field(default_factory=set)
    ios_cloned: set[str] = field(default_factory=set)


class DevicePool:
    """Manage device leases with serialized initialization and shutdown.

    The state condition protects admission and bookkeeping; no SDK/subprocess I/O
    holds that lock. Initialization publishes an inventory atomically. Shutdown
    rejects new leases, wakes waiters, drains release cleanups and detaches owned
    resources before best-effort teardown. Calls must return the exact lease from
    acquire(); stale, foreign and duplicate releases are ignored.
    """

    def __init__(self, platform: str, max_devices: int = 4) -> None:
        self.platform = platform.lower()
        self._max_devices = max(1, min(max_devices, MAX_DEVICES_LIMIT))
        self._available: List[DeviceSlot] = []
        self._in_use: Dict[str, DeviceSlot] = {}
        self._releasing: Dict[str, DeviceSlot] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._lifecycle_lock = threading.Lock()
        self._android_processes: Dict[int, subprocess.Popen] = {}
        self._ios_booted_by_pool: Set[str] = set()
        self._ios_cloned_by_pool: Set[str] = set()
        self._state = "new"
        self._generation = 0

    def initialize(self) -> None:
        """Initialize once, or reopen after a completed shutdown.

        Lifecycle calls are serialized. Device discovery/boot runs in a private
        inventory and does not block state readers. Partial startup is cleaned
        before its original exception is propagated; no partial slots are leased.
        """
        with self._lifecycle_lock:
            with self._condition:
                if self._state == "ready":
                    return
                if self._state == "closing":
                    raise RuntimeError("DevicePool shutdown incomplete; call shutdown() first")
                self._state = "initializing"
                self._generation += 1
            inventory = _DeviceInventory()
            try:
                if self.platform == "android":
                    self._init_android(inventory)
                elif self.platform == "ios":
                    self._init_ios(inventory)
                else:
                    raise ValueError(f"Unsupported platform: {self.platform}")
            except BaseException:
                try:
                    self._cleanup_inventory(inventory)
                finally:
                    with self._condition:
                        self._state = "closed"
                        self._condition.notify_all()
                raise
            with self._condition:
                self._available = inventory.available
                self._android_processes = inventory.android_processes
                self._ios_booted_by_pool = inventory.ios_booted
                self._ios_cloned_by_pool = inventory.ios_cloned
                self._state = "ready"
                self._condition.notify_all()
                logger.info("DevicePool initialized: platform=%s, slots=%d",
                            self.platform, len(self._available))

    def total_slots(self) -> int:
        """Return ready capacity, including leased/releasing slots, or zero when closed."""
        with self._condition:
            if self._state != "ready":
                return 0
            return len(self._available) + len(self._in_use)

    def acquire(self, timeout: float = 300) -> DeviceSlot:
        """Wait for a lease; raise RuntimeError if this generation closes.

        TimeoutError means a ready pool had no available slot before the deadline.
        A caller waiting across shutdown cannot acquire from a subsequent restart.
        """
        deadline = time.monotonic() + timeout
        with self._condition:
            generation = self._generation
            while True:
                if self._state != "ready" or self._generation != generation:
                    raise RuntimeError("DevicePool is not initialized or has shut down")
                if self._available:
                    # New identity for each lease prevents an old/duplicate return
                    # from releasing the same device after another worker borrows it.
                    slot = replace(self._available.pop(0))
                    self._in_use[slot.device_id] = slot
                    logger.debug("Acquired device: %s", slot.device_id)
                    return slot
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"No device available within {timeout}s "
                        f"(in_use={len(self._in_use)}, available={len(self._available)})"
                    )
                self._condition.wait(timeout=remaining)

    def release(self, slot: DeviceSlot) -> None:
        """Clean one current lease outside the state lock, then return it if ready.

        Duplicate/foreign/old leases do not run cleanup commands. Shutdown waits
        for already-started release cleanups before stopping owned devices. A
        lease returned after closing starts is discarded, never reintroduced.
        """
        with self._condition:
            if (self._state != "ready" or self._in_use.get(slot.device_id) is not slot
                    or slot.device_id in self._releasing):
                return
            self._releasing[slot.device_id] = slot
        try:
            self._cleanup_slot(slot)
        except Exception as exc:
            logger.warning("Device cleanup failed for %s before release: %s", slot.device_id, exc)
        finally:
            with self._condition:
                if self._releasing.get(slot.device_id) is slot:
                    self._releasing.pop(slot.device_id)
                if self._in_use.get(slot.device_id) is slot:
                    self._in_use.pop(slot.device_id)
                    if self._state == "ready":
                        self._available.append(slot)
                self._condition.notify_all()

    def _cleanup_slot(self, slot: DeviceSlot) -> None:
        """在设备归还前的最小化状态清理。

        设计原则：
        - 越可能“不为”，仅限于安全的背景进程清理与退出项目页面；
        - 全部调用都加上超时，不能干扰下一轮调度。
        """
        if slot.platform == "android":
            adb_path = get_adb_path()
            # 先回到桌面，并杀掉背景进程（不会影响前台与系统服务）。
            for cmd in (
                [adb_path, "-s", slot.device_id, "shell", "input", "keyevent", "3"],
                [adb_path, "-s", slot.device_id, "shell", "am", "kill-all"],
            ):
                try:
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except Exception as exc:
                    logger.warning(
                        "adb cleanup step %s failed on %s: %s",
                        cmd[3:], slot.device_id, exc,
                    )
        elif slot.platform == "ios":
            # iOS 模拟器上“杀测试应用”需要 bundle id，本层无法可靠获取；
            # executor 在测试完成后会按需 uninstall 应用。
            # 在这里执行安全的最小动作：调用 simctl listapps 仅作为连通性探测，
            # 实际进程清理取决于业务层。不可用时静默跳过。
            try:
                subprocess.run(
                    ["xcrun", "simctl", "listapps", slot.device_id],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except Exception:
                # 仅作为连通性探测，失败不警告。
                pass

    def shutdown(self) -> None:
        """Close admission and best-effort stop resources created/booted by this pool.

        Concurrent calls are idempotent and wait for the first teardown. Waiting
        acquirers fail promptly. Already-running release cleanup is drained, but
        borrowed evaluations are not gracefully drained: callers should join their
        workers first. Slow teardown does not hold the state lock. OS/SDK failures
        are logged; force-killing the process cannot guarantee external cleanup.
        """
        with self._lifecycle_lock:
            with self._condition:
                if self._state in {"new", "closed"}:
                    return
                self._state = "closing"
                self._generation += 1
                self._condition.notify_all()
                while self._releasing:
                    self._condition.wait()
                inventory = _DeviceInventory(
                    self._available, self._android_processes,
                    self._ios_booted_by_pool, self._ios_cloned_by_pool,
                )
                self._available = []
                self._in_use.clear()
                self._android_processes = {}
                self._ios_booted_by_pool = set()
                self._ios_cloned_by_pool = set()
            try:
                self._cleanup_inventory(inventory)
            finally:
                with self._condition:
                    self._state = "closed"
                    self._condition.notify_all()
            logger.info("DevicePool shut down: platform=%s", self.platform)

    def _cleanup_inventory(self, inventory: _DeviceInventory) -> None:
        """Tear down a detached inventory without accessing shared resource maps."""
        try:
            if self.platform == "android":
                self._shutdown_android(inventory.android_processes)
            elif self.platform == "ios":
                self._shutdown_ios(inventory.ios_booted, inventory.ios_cloned)
        except Exception as exc:
            logger.warning("DevicePool best-effort cleanup failed: %s", exc)

    # -- Android internals ---------------------------------------------------

    def _init_android(self, inventory: _DeviceInventory) -> None:
        """Populate the pool with Android emulators.

        Strategy:
        1) Reuse already-online ``emulator-XXXX`` devices first (no extra boot wait).
        2) Spawn additional emulators on free ports only as needed.
        3) Wait for fresh emulators to boot in parallel.

        Raises:
            RuntimeError: If neither online emulators nor newly started ones are
                          available — caller can decide how to handle (no silent
                          empty pool).
        """
        from concurrent.futures import ThreadPoolExecutor

        emulator_path = os.path.join(get_android_home(), "emulator", "emulator")
        adb_path = get_adb_path()

        # 1) Reuse already-running emulators if any.
        online_ports = self._list_online_android_emulator_ports(adb_path)
        online_avd_names: set[str] = set()
        for port in online_ports:
            if len(inventory.available) >= self._max_devices:
                break
            device_id = f"emulator-{port}"
            inventory.available.append(
                DeviceSlot(device_id=device_id, platform="android", port=port)
            )
            # Detect which AVD this emulator is using so we don't try to launch
            # another instance of the same AVD later.
            avd = self._get_emulator_avd_name(adb_path, port)
            if avd:
                online_avd_names.add(avd)
            logger.info("Reusing online Android emulator: %s (avd=%s)", device_id, avd or "unknown")

        remaining = self._max_devices - len(inventory.available)
        if remaining <= 0:
            return

        # 2) List AVDs to start fresh emulators.
        try:
            result = subprocess.run(
                [emulator_path, "-list-avds"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"emulator binary not found at {emulator_path}; "
                "check ANDROID_HOME and SDK installation"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"`emulator -list-avds` timed out after 15s ({emulator_path}); "
                "the emulator subsystem may be hung"
            ) from e

        avds = [line.strip() for line in (result.stdout or "").strip().split("\n") if line.strip()]
        if not avds:
            if inventory.available:
                logger.warning(
                    "No AVDs available; using %d already-online emulator(s) only",
                    len(inventory.available),
                )
                return
            raise RuntimeError(
                f"No Android AVDs found via `{emulator_path} -list-avds`. "
                "Create one with `avdmanager create avd ...` or via Android Studio."
            )

        # Exclude AVDs already occupied by online emulators.
        available_avds = [a for a in avds if a not in online_avd_names]
        if not available_avds:
            logger.info(
                "All %d AVD(s) are already in use by online emulators; "
                "no additional launch needed",
                len(avds),
            )
            return

        avd_name = available_avds[0]

        # Android emulator does NOT support multiple instances of the SAME AVD.
        # Limit remaining to the number of distinct AVAILABLE (not-in-use) AVDs.
        remaining = min(remaining, len(available_avds))
        if remaining <= 0:
            logger.info(
                "Already have %d online emulator(s) which matches available AVD count (%d); "
                "no additional launch needed",
                len(inventory.available), len(available_avds),
            )
            return

        logger.info("Using AVD: %s (need to start %d emulator(s))", avd_name, remaining)

        # 3) Launch additional emulators on free ports.
        # Each new emulator uses a distinct AVD to avoid "already running" conflict.
        used_ports = set(online_ports) | {slot.port for slot in inventory.available}
        new_ports: list[int] = []
        for i in range(remaining):
            avd_to_use = available_avds[i % len(available_avds)]
            port = _ANDROID_BASE_PORT
            while port in used_ports:
                port += 2
            used_ports.add(port)
            cmd = (
                f"{emulator_path} -avd {avd_to_use} -port {port} "
                f"-no-snapshot -no-window -no-audio"
            )
            logger.info("Starting emulator on port %d (avd=%s): %s", port, avd_to_use, cmd)
            try:
                proc = run_command_async(cmd)
                inventory.android_processes[port] = proc
                new_ports.append(port)
            except Exception as e:  # noqa: BLE001
                logger.error("Failed to start emulator on port %d: %s", port, e)

        if not new_ports:
            if inventory.available:
                logger.warning(
                    "All new emulator launches failed; falling back to %d online emulator(s)",
                    len(inventory.available),
                )
                return
            raise RuntimeError(
                f"Failed to spawn any Android emulator process (avd={avd_name}); "
                "see preceding errors"
            )

        # 4) Wait for fresh emulators to boot in parallel.
        with ThreadPoolExecutor(max_workers=max(1, len(new_ports))) as ex:
            futures = {
                port: ex.submit(self._wait_for_android_boot, adb_path, port, 240)
                for port in new_ports
            }
            for port, fut in futures.items():
                device_id = f"emulator-{port}"
                try:
                    booted = fut.result()
                except Exception as e:  # noqa: BLE001
                    booted = False
                    logger.error("Boot wait raised on %s: %s", device_id, e)
                if booted:
                    inventory.available.append(
                        DeviceSlot(device_id=device_id, platform="android", port=port)
                    )
                else:
                    logger.warning(
                        "Emulator on port %d did not boot within timeout; skipping",
                        port,
                    )
                    proc = inventory.android_processes.get(port)
                    if proc is not None:
                        self._shutdown_android({port: proc})
                        inventory.android_processes.pop(port, None)

        if not inventory.available:
            raise RuntimeError(
                f"All {len(new_ports)} Android emulator(s) failed to boot within timeout. "
                "Check emulator logs and AVD configuration."
            )

    @staticmethod
    def _get_emulator_avd_name(adb_path: str, port: int) -> str | None:
        """Query the AVD name running on the given emulator port via telnet protocol."""
        device_id = f"emulator-{port}"
        try:
            result = subprocess.run(
                [adb_path, "-s", device_id, "emu", "avd", "name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Output is typically: "<avd_name>\nOK"
            lines = [l.strip() for l in (result.stdout or "").strip().splitlines() if l.strip() and l.strip() != "OK"]
            return lines[0] if lines else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _list_online_android_emulator_ports(adb_path: str) -> list[int]:
        """Return ports of currently-online ``emulator-XXXX`` devices via ``adb devices``."""
        try:
            result = subprocess.run(
                [adb_path, "devices"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("`adb devices` failed: %s", e)
            return []

        ports: list[int] = []
        for line in (result.stdout or "").splitlines()[1:]:
            line = line.strip()
            if not line or "\tdevice" not in line:
                continue
            name = line.split("\t", 1)[0].strip()
            if not name.startswith("emulator-"):
                continue
            try:
                ports.append(int(name.split("-", 1)[1]))
            except (ValueError, IndexError):
                continue
        return ports

    @staticmethod
    def _wait_for_android_boot(adb_path: str, port: int, timeout: int = 180) -> bool:
        """Poll ``adb shell getprop sys.boot_completed`` until it returns ``1``."""
        device_id = f"emulator-{port}"
        deadline = time.monotonic() + timeout
        logger.info("Waiting for %s to boot (timeout=%ds)\u2026", device_id, timeout)
    
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    [adb_path, "-s", device_id, "shell", "getprop", "sys.boot_completed"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip() == "1":
                    logger.info("%s booted successfully", device_id)
                    # Wait for PackageManager to be ready
                    pm_deadline = time.monotonic() + 60
                    while time.monotonic() < pm_deadline:
                        try:
                            pm_result = subprocess.run(
                                [adb_path, "-s", device_id, "shell", "pm", "list", "packages"],
                                capture_output=True, text=True, timeout=10,
                            )
                            if pm_result.returncode == 0 and pm_result.stdout.strip():
                                logger.info("%s PackageManager ready", device_id)
                                return True
                        except (subprocess.TimeoutExpired, OSError) as e:
                            logger.debug("PM check for %s raised: %s", device_id, e)
                        time.sleep(2)
                    # PM not ready after 60s — still return True, let install retry handle it
                    logger.warning("%s PackageManager not ready after 60s", device_id)
                    return True
                # Device not ready yet (offline / not found) — continue polling
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.debug("Boot check for %s raised: %s", device_id, e)
            time.sleep(2)
    
        return False

    def _shutdown_android(self, processes: dict[int, subprocess.Popen]) -> None:
        """Stop only owned emulator processes; isolate failures and reap exits."""
        try:
            adb_path = get_adb_path() if processes else None
        except Exception as exc:
            adb_path = None
            logger.warning("adb unavailable during cleanup; using process handles: %s", exc)
        for port, proc in list(processes.items()):
            device_id = f"emulator-{port}"
            if adb_path:
                try:
                    subprocess.run([adb_path, "-s", device_id, "emu", "kill"],
                                   capture_output=True, text=True, timeout=30)
                except Exception as exc:
                    logger.warning("adb emu kill failed for %s: %s", device_id, exc)
            try:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=10)
                    except Exception:
                        proc.kill()
                        proc.wait(timeout=10)
            except Exception as exc:
                logger.warning("Process cleanup failed for %s: %s", device_id, exc)
        processes.clear()

    # -- iOS internals -------------------------------------------------------

    def _init_ios(self, inventory: _DeviceInventory) -> None:
        """Boot *n* iOS simulators, cloning if necessary."""
        # 1. Query all available iPhone simulators
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "list", "devices", "available", "-j"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            data = json.loads(result.stdout)
        except Exception as e:
            logger.error("Failed to query iOS simulators: %s", e)
            return

        devices_raw = data.get("devices", {})

        # 2. Separate into already-booted and shut-down candidates
        booted: List[tuple[str, str]] = []  # (name, udid) — pre-existing
        shut_down: List[tuple[str, str]] = []  # (name, udid) — available to boot

        for runtime, device_list in devices_raw.items():
            if "iOS" not in runtime:
                continue
            for dev in device_list:
                name = dev.get("name", "")
                if "iPhone" not in name:
                    continue
                if not dev.get("isAvailable", False):
                    continue
                udid = dev.get("udid", "")
                if dev.get("state") == "Booted":
                    booted.append((name, udid))
                else:
                    shut_down.append((name, udid))

        # Sort by preference
        booted.sort(key=lambda it: _ios_simulator_priority(it[0]))
        shut_down.sort(key=lambda it: _ios_simulator_priority(it[0]))

        # 3. Boot the required number of simulators
        needed = self._max_devices

        # Use pre-booted simulators first (but don't track them — we won't
        # shut them down on pool shutdown)
        for name, udid in booted:
            if needed <= 0:
                break
            inventory.available.append(
                DeviceSlot(device_id=udid, platform="ios", port=None)
            )
            logger.info("Using pre-booted simulator: %s (%s)", name, udid)
            needed -= 1

        # Boot shut-down simulators
        for name, udid in shut_down:
            if needed <= 0:
                break
            if self._boot_ios_simulator(udid, name):
                inventory.ios_booted.add(udid)
                inventory.available.append(
                    DeviceSlot(device_id=udid, platform="ios", port=None)
                )
                needed -= 1

        # 4. Clone if still not enough
        if needed > 0 and booted:
            # Use the highest-priority booted simulator as the clone source
            source_name, source_udid = booted[0]
            for idx in range(needed):
                clone_name = f"{source_name}-pool-{idx}"
                clone_udid = self._clone_ios_simulator(source_udid, clone_name)
                if clone_udid:
                    inventory.ios_cloned.add(clone_udid)
                    if not self._boot_ios_simulator(clone_udid, clone_name):
                        continue
                    inventory.ios_booted.add(clone_udid)
                    inventory.available.append(
                        DeviceSlot(device_id=clone_udid, platform="ios", port=None)
                    )
        elif needed > 0 and shut_down:
            # Fallback: clone from the highest-priority shut-down simulator
            source_name, source_udid = shut_down[0]
            for idx in range(needed):
                clone_name = f"{source_name}-pool-{idx}"
                clone_udid = self._clone_ios_simulator(source_udid, clone_name)
                if clone_udid:
                    inventory.ios_cloned.add(clone_udid)
                    if not self._boot_ios_simulator(clone_udid, clone_name):
                        continue
                    inventory.ios_booted.add(clone_udid)
                    inventory.available.append(
                        DeviceSlot(device_id=clone_udid, platform="ios", port=None)
                    )

    @staticmethod
    def _boot_ios_simulator(udid: str, name: str) -> bool:
        """Boot an iOS simulator by UDID. Returns True on success."""
        logger.info("Booting iOS simulator: %s (%s)", name, udid)
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "boot", udid],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info("Simulator booted: %s", name)
                return True
            # simctl boot returns error if already booted — treat as success
            if "already booted" in result.stderr.lower():
                return True
            logger.warning("Failed to boot %s: %s", name, result.stderr.strip())
        except Exception as e:
            logger.warning("Exception booting %s: %s", name, e)
        return False

    @staticmethod
    def _clone_ios_simulator(source_udid: str, new_name: str) -> str | None:
        """Clone an iOS simulator. Returns the new UDID on success."""
        logger.info("Cloning simulator %s -> %s", source_udid, new_name)
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "clone", source_udid, new_name],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                clone_udid = result.stdout.strip()
                logger.info("Cloned simulator: %s -> %s", new_name, clone_udid)
                return clone_udid
            logger.warning("Clone failed: %s", result.stderr.strip())
        except Exception as e:
            logger.warning("Exception cloning simulator: %s", e)
        return None

    def _shutdown_ios(self, booted: set[str], cloned: set[str]) -> None:
        """Shut down simulators booted by the pool and delete cloned ones."""
        for udid in list(booted):
            logger.info("Shutting down simulator: %s", udid)
            try:
                subprocess.run(
                    ["xcrun", "simctl", "shutdown", udid],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception as e:
                logger.warning("Failed to shutdown simulator %s: %s", udid, e)

        for udid in list(cloned):
            logger.info("Deleting cloned simulator: %s", udid)
            try:
                subprocess.run(
                    ["xcrun", "simctl", "delete", udid],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception as e:
                logger.warning("Failed to delete simulator %s: %s", udid, e)

        booted.clear()
        cloned.clear()
