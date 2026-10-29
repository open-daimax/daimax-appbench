"""Deterministic lifecycle races; no emulator, simulator or SDK is invoked."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from evalapp.utils.device_pool import DevicePool, DeviceSlot


class Task:
    """Capture thread outcomes without unhandled-thread warnings."""

    def __init__(self, call: Callable[[], Any]) -> None:
        self.value: Any = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        def run() -> None:
            try:
                self.value = call()
            except BaseException as exc:
                self.error = exc
            finally:
                self.done.set()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def join(self) -> None:
        self.thread.join(3)
        assert not self.thread.is_alive(), 'Lifecycle operation did not finish'


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> DevicePool:
    result = DevicePool('android', max_devices=1)
    def initialize(*args: Any) -> None:
        available = args[0].available if args else result._available
        available.append(DeviceSlot('emulator-5554', 'android', 5554))
    monkeypatch.setattr(result, '_init_android', initialize)
    monkeypatch.setattr(result, '_shutdown_android', lambda *args: None)
    monkeypatch.setattr(result, '_cleanup_slot', lambda slot: None)
    result.initialize()
    return result


def test_shutdown_wakes_waiting_acquire(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    pool.acquire()
    waiting = threading.Event()
    original = pool._condition.wait
    def wait(timeout: float | None = None) -> bool:
        waiting.set()
        return original(timeout)
    monkeypatch.setattr(pool._condition, 'wait', wait)
    caller = Task(lambda: pool.acquire(timeout=1.5))
    assert waiting.wait(1)
    pool.shutdown()
    completed = caller.done.wait(0.5)
    caller.join()
    assert completed, 'Closing must wake waiters instead of waiting for acquire timeout'
    assert isinstance(caller.error, RuntimeError)


def test_slow_shutdown_does_not_hold_the_state_lock(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, proceed = threading.Event(), threading.Event()
    def stop(*args: Any) -> None:
        entered.set()
        assert proceed.wait(3)
    monkeypatch.setattr(pool, '_shutdown_android', stop)
    closing = Task(pool.shutdown)
    assert entered.wait(1)
    reader = Task(pool.total_slots)
    borrower = Task(lambda: pool.acquire(timeout=0))
    try:
        read_completed = reader.done.wait(0.5)
        acquire_completed = borrower.done.wait(0.5)
    finally:
        proceed.set()
        closing.join(); reader.join(); borrower.join()
    assert read_completed and acquire_completed
    assert reader.value == 0
    assert isinstance(borrower.error, RuntimeError)
    assert closing.error is None


def test_late_release_cannot_return_an_old_lease_after_restart(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    old = pool.acquire()
    pool.shutdown()
    pool.initialize()
    current = pool.acquire()
    cleanups = []
    monkeypatch.setattr(pool, '_cleanup_slot', lambda slot: cleanups.append(slot))
    pool.release(old)
    assert cleanups == [], 'Stale leases must not run device commands against a new generation'
    with pytest.raises(TimeoutError):
        pool.acquire(timeout=0)
    pool.release(current)
    assert pool.total_slots() == 1


def test_duplicate_release_runs_cleanup_only_once(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    slot = pool.acquire()
    entered, proceed = threading.Event(), threading.Event()
    cleanups = []
    def cleanup(value: DeviceSlot) -> None:
        cleanups.append(value)
        entered.set()
        assert proceed.wait(3)
    monkeypatch.setattr(pool, '_cleanup_slot', cleanup)
    first = Task(lambda: pool.release(slot))
    assert entered.wait(1)
    second = Task(lambda: pool.release(slot))
    try:
        duplicate_ignored = second.done.wait(0.5)
    finally:
        proceed.set()
        first.join(); second.join()
    assert duplicate_ignored and cleanups == [slot]
    assert first.error is None and second.error is None
    pool.acquire()
    with pytest.raises(TimeoutError):
        pool.acquire(timeout=0)


def test_shutdown_waits_for_inflight_release_before_stopping_device(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    slot = pool.acquire()
    entered, proceed, stopped = threading.Event(), threading.Event(), threading.Event()
    order = []
    def cleanup(value: DeviceSlot) -> None:
        entered.set()
        assert proceed.wait(3)
        order.append('release-cleaned')
    def stop(*args: Any) -> None:
        order.append('device-stopped')
        stopped.set()
    monkeypatch.setattr(pool, '_cleanup_slot', cleanup)
    monkeypatch.setattr(pool, '_shutdown_android', stop)
    releasing = Task(lambda: pool.release(slot))
    assert entered.wait(1)
    closing = Task(pool.shutdown)
    try:
        stopped_early = stopped.wait(0.3)
    finally:
        proceed.set()
        releasing.join(); closing.join()
    assert not stopped_early
    assert order == ['release-cleaned', 'device-stopped']
    assert pool.total_slots() == 0


def test_shutdown_is_idempotent_for_concurrent_callers(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, proceed = threading.Event(), threading.Event()
    stops = []
    def stop(*args: Any) -> None:
        stops.append(True); entered.set()
        assert proceed.wait(3)
    monkeypatch.setattr(pool, '_shutdown_android', stop)
    first = Task(pool.shutdown)
    assert entered.wait(1)
    second = Task(pool.shutdown)
    proceed.set()
    first.join(); second.join()
    assert stops == [True]
    assert first.error is None and second.error is None


def test_partial_initialization_is_cleaned_and_never_published(monkeypatch: pytest.MonkeyPatch) -> None:
    result = DevicePool('android', 1)
    sentinel = object()
    stopped = []
    def initialize(*args: Any) -> None:
        available = args[0].available if args else result._available
        processes = args[0].android_processes if args else result._android_processes
        available.append(DeviceSlot('emulator-5554', 'android', 5554))
        processes[5554] = sentinel
        raise RuntimeError('fixture initialization failure')
    def stop(*args: Any) -> None:
        processes = args[0] if args else result._android_processes
        stopped.extend(processes.values())
    monkeypatch.setattr(result, '_init_android', initialize)
    monkeypatch.setattr(result, '_shutdown_android', stop)
    with pytest.raises(RuntimeError, match='fixture initialization failure'):
        result.initialize()
    assert stopped == [sentinel]
    assert result.total_slots() == 0
    with pytest.raises(RuntimeError):
        result.acquire(timeout=0)


def test_initialization_publishes_slots_atomically(monkeypatch: pytest.MonkeyPatch) -> None:
    result = DevicePool('android', 1)
    entered, proceed = threading.Event(), threading.Event()
    def initialize(*args: Any) -> None:
        available = args[0].available if args else result._available
        available.append(DeviceSlot('emulator-5554', 'android', 5554))
        entered.set()
        assert proceed.wait(3)
    monkeypatch.setattr(result, '_init_android', initialize)
    starting = Task(result.initialize)
    assert entered.wait(1)
    reader = Task(result.total_slots)
    borrower = Task(lambda: result.acquire(timeout=0))
    try:
        visible_early = reader.done.wait(0.5)
        rejected_early = borrower.done.wait(0.5)
    finally:
        proceed.set()
        starting.join(); reader.join(); borrower.join()
    assert visible_early and rejected_early
    assert reader.value == 0 and isinstance(borrower.error, RuntimeError)
    assert result.total_slots() == 1


def test_waiter_cannot_borrow_from_a_later_generation(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    pool.acquire()
    waiting, awake, resume = threading.Event(), threading.Event(), threading.Event()
    original = pool._condition.wait
    def wait(timeout: float | None = None) -> bool:
        waiting.set()
        result = original(timeout)
        # Delay the woken worker outside the condition to allow a full restart.
        pool._condition.release()
        try:
            awake.set()
            assert resume.wait(3)
        finally:
            pool._condition.acquire()
        return result
    monkeypatch.setattr(pool._condition, 'wait', wait)
    borrower = Task(lambda: pool.acquire(timeout=2))
    assert waiting.wait(1)
    try:
        pool.shutdown()
        with pool._condition:
            pool._condition.notify_all()
        assert awake.wait(1)
        pool.initialize()
    finally:
        resume.set(); borrower.join()
    assert isinstance(borrower.error, RuntimeError)
    assert pool.acquire(timeout=0).device_id == 'emulator-5554'


def test_release_cleanup_failure_does_not_strand_a_lease(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    slot = pool.acquire()
    def fail(value: DeviceSlot) -> None:
        raise RuntimeError('fixture release failure')
    monkeypatch.setattr(pool, '_cleanup_slot', fail)
    pool.release(slot)
    assert pool.acquire(timeout=0).device_id == slot.device_id
    pool.shutdown()
    assert pool.total_slots() == 0


class Process:
    """Small subprocess handle fake with controllable failure paths."""

    def __init__(self, failure: str = '') -> None:
        self.failure = failure
        self.terminated = False
        self.killed = False
        self.reaped = False

    def poll(self) -> None:
        if self.failure == 'poll':
            raise OSError('fixture broken process handle')
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float) -> int:
        import subprocess
        if self.failure == 'timeout' and not self.killed:
            raise subprocess.TimeoutExpired('fixture process', timeout)
        self.reaped = True
        return 0


@pytest.mark.parametrize('failure', ['poll', 'timeout'])
def test_android_cleanup_isolates_failed_handles_and_reaps_processes(
    failure: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    import evalapp.utils.device_pool as module
    result = DevicePool('android', 2)
    bad, good = Process(failure), Process()
    def initialize(inventory: Any) -> None:
        inventory.available.extend([DeviceSlot('emulator-5554', 'android', 5554),
                                    DeviceSlot('emulator-5556', 'android', 5556)])
        inventory.android_processes.update({5554: bad, 5556: good})
    monkeypatch.setattr(result, '_init_android', initialize)
    monkeypatch.setattr(module, 'get_adb_path', lambda: '/fixture/adb')
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    result.initialize(); result.shutdown()
    assert good.terminated and good.reaped
    if failure == 'timeout':
        assert bad.killed and bad.reaped
    assert result.total_slots() == 0
    with pytest.raises(RuntimeError):
        result.acquire(timeout=0)


def test_android_process_fallback_works_without_adb(monkeypatch: pytest.MonkeyPatch) -> None:
    import evalapp.utils.device_pool as module
    result = DevicePool('android', 1)
    proc = Process()
    def initialize(inventory: Any) -> None:
        inventory.available.append(DeviceSlot('emulator-5554', 'android', 5554))
        inventory.android_processes[5554] = proc
    def unavailable() -> str:
        raise FileNotFoundError('fixture missing adb')
    monkeypatch.setattr(result, '_init_android', initialize)
    monkeypatch.setattr(module, 'get_adb_path', unavailable)
    result.initialize(); result.shutdown()
    assert proc.terminated and proc.reaped


def test_failed_ios_clone_boot_still_deletes_owned_clone(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from types import SimpleNamespace
    import evalapp.utils.device_pool as module
    commands = []
    devices = {'devices': {'com.apple.CoreSimulator.SimRuntime.iOS-fixture': [
        {'name': 'iPhone 16', 'udid': 'external-booted', 'state': 'Booted', 'isAvailable': True}]}}
    def run(command: list[str], **kwargs: Any) -> Any:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(devices), stderr='')
    monkeypatch.setattr(module.subprocess, 'run', run)
    result = DevicePool('ios', 2)
    monkeypatch.setattr(result, '_clone_ios_simulator', lambda *args: 'owned-clone')
    monkeypatch.setattr(result, '_boot_ios_simulator', lambda *args: False)
    result.initialize(); result.shutdown()
    assert ['xcrun', 'simctl', 'delete', 'owned-clone'] in commands
    assert not any(command[2:]==['shutdown', 'external-booted'] for command in commands)


def test_cleanup_exception_does_not_leave_pool_logically_open(pool: DevicePool, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any) -> None:
        raise RuntimeError('fixture shutdown failure')
    monkeypatch.setattr(pool, '_shutdown_android', fail)
    pool.shutdown()
    assert pool.total_slots() == 0
    with pytest.raises(RuntimeError):
        pool.acquire(timeout=0)
    pool.initialize()
    assert pool.acquire(timeout=0).device_id == 'emulator-5554'


def test_duplicate_old_lease_cannot_release_a_new_lease_in_same_generation(
    pool: DevicePool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = pool.acquire()
    pool.release(old)
    current = pool.acquire()
    cleanups = []
    monkeypatch.setattr(pool, '_cleanup_slot', lambda slot: cleanups.append(slot))
    assert current is not old
    pool.release(old)
    assert cleanups == []
    with pytest.raises(TimeoutError):
        pool.acquire(timeout=0)
    pool.release(current)
