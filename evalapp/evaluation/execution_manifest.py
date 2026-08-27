"""Execution Manifest: persistent per-(sample, platform) execution status tracker.

The manifest is stored as ``execution_manifest.json`` at the root of a workspace
directory and tracks generation/evaluation status of every sample-platform pair.
It is the single source of truth used by recovery, reporting, and incremental
re-execution flows.

Design points:
* **Atomic writes** — temp file + ``os.replace`` to survive interruption.
* **Thread-safe updates** — all mutating ops take a ``threading.Lock``.
* **Backward compatible** — workspaces lacking a manifest continue to work; the
  manifest is created lazily on first access.
* **Non-invasive** — manifest is purely an observability layer; it never alters
  business behavior (sample order, error handling, etc.) of upstream callers.

Phase status values:
    ``pending`` → ``running`` → ``completed`` | ``failed`` | ``skipped``

Overall status rules (per item):
    * Any phase failed → ``failed``
    * Item explicitly skipped → ``skipped``
    * Any phase running → ``running``
    * All declared phases completed → ``completed``
    * Otherwise → ``pending``
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..utils.logging import get_logger

logger = get_logger(__name__)

MANIFEST_FILENAME = "execution_manifest.json"

# Declared phases tracked by manifest. Keep ordered for predictable iteration.
PHASES: tuple[str, ...] = ("generate", "evaluate")

# Valid phase status values
PHASE_PENDING = "pending"
PHASE_RUNNING = "running"
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"
PHASE_SKIPPED = "skipped"

# Status priority for monotonic per-phase merge across processes.
# Higher value = higher priority; only higher-priority states are allowed to
# overwrite lower-priority ones during cross-process save() merge.
_STATUS_PRIORITY: dict[str, int] = {
    PHASE_PENDING: 0,
    PHASE_RUNNING: 1,
    PHASE_SKIPPED: 2,
    PHASE_FAILED: 3,
    PHASE_COMPLETED: 4,
}


def _status_priority(status: Any) -> int:
    """Return the priority rank of ``status`` (unknown values rank below pending)."""
    if not isinstance(status, str):
        return -1
    return _STATUS_PRIORITY.get(status, -1)


def _merge_item(
    memory_item: dict[str, Any], disk_item: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge an in-memory item into the disk version using per-phase priority.

    Rules:
        * If ``disk_item`` is ``None`` → return a deep copy of ``memory_item``.
        * For each phase in ``phases``: keep the version whose ``status`` has
          higher priority (see ``_STATUS_PRIORITY``). Ties favor disk to avoid
          regressing freshly-written state with a stale in-memory snapshot.
        * For ``overall_status``: take the higher-priority value.
        * Static identity fields (``sample_id``/``sample_name``/``platform``)
          prefer the in-memory version (they don't affect correctness, just
          carry the latest display name).
    """
    if disk_item is None:
        return copy.deepcopy(memory_item)

    merged: dict[str, Any] = copy.deepcopy(disk_item)

    # Static identity fields — prefer memory.
    for field in ("sample_id", "sample_name", "platform"):
        mem_val = memory_item.get(field)
        if mem_val:
            merged[field] = mem_val

    # Per-phase monotonic merge.
    mem_phases = memory_item.get("phases") or {}
    disk_phases = merged.get("phases") or {}
    out_phases: dict[str, dict[str, Any]] = {
        name: copy.deepcopy(p) for name, p in disk_phases.items()
    }
    for phase_name, mem_phase in mem_phases.items():
        if not isinstance(mem_phase, dict):
            continue
        disk_phase = out_phases.get(phase_name)
        if disk_phase is None:
            out_phases[phase_name] = copy.deepcopy(mem_phase)
            continue
        mem_pri = _status_priority(mem_phase.get("status"))
        disk_pri = _status_priority(disk_phase.get("status"))
        if mem_pri > disk_pri:
            out_phases[phase_name] = copy.deepcopy(mem_phase)
        # else: keep disk version (do not let stale memory regress disk)
    merged["phases"] = out_phases

    # overall_status — priority-based.
    mem_overall = memory_item.get("overall_status", PHASE_PENDING)
    disk_overall = merged.get("overall_status", PHASE_PENDING)
    if _status_priority(mem_overall) > _status_priority(disk_overall):
        merged["overall_status"] = mem_overall

    return merged


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve_sample_meta(plan_item: Any) -> tuple[str, str, str]:
    """Extract (sample_id, sample_name, platform) from a plan item.

    Accepts dicts of multiple shapes (containing ``sample`` object, or flat
    ``sample_id`` / ``sample_name`` / ``platform`` keys), as well as tuples
    ``(sample, platform[, ...])``.
    """
    if isinstance(plan_item, dict):
        sample_obj = plan_item.get("sample")
        sample_id = plan_item.get("sample_id")
        sample_name = plan_item.get("sample_name")
        platform = plan_item.get("platform")
        if sample_obj is not None:
            sample_id = sample_id or getattr(sample_obj, "sample_id", "") or ""
            sample_name = sample_name or getattr(sample_obj, "title", "") or sample_id
        sample_id = sample_id or ""
        sample_name = sample_name or sample_id
        platform = platform or ""
        return str(sample_id), str(sample_name), str(platform)

    # Tuple/list support: (sample, platform, ...)
    if isinstance(plan_item, (tuple, list)) and len(plan_item) >= 2:
        sample_obj = plan_item[0]
        platform = plan_item[1]
        sample_id = getattr(sample_obj, "sample_id", "") or ""
        sample_name = getattr(sample_obj, "title", "") or sample_id
        return str(sample_id), str(sample_name), str(platform)

    raise TypeError(f"Unsupported plan item type: {type(plan_item)!r}")


class ManifestItem:
    """Lightweight helper around a single manifest item dict.

    The canonical storage is a plain dict so the JSON round-trip stays trivial;
    this class is mostly used by callers that prefer attribute access.
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def sample_id(self) -> str:
        return self._data.get("sample_id", "")

    @property
    def sample_name(self) -> str:
        return self._data.get("sample_name", "")

    @property
    def platform(self) -> str:
        return self._data.get("platform", "")

    @property
    def phases(self) -> dict[str, dict[str, Any]]:
        return self._data.setdefault("phases", {})

    @property
    def overall_status(self) -> str:
        return self._data.get("overall_status", PHASE_PENDING)

    def to_dict(self) -> dict[str, Any]:
        return self._data


class ExecutionManifest:
    """Persistent manifest tracking sample×platform execution status."""

    def __init__(
        self,
        workspace_path: Path | str,
        data: dict[str, Any],
        lock: threading.Lock | None = None,
    ) -> None:
        self.workspace_path = Path(workspace_path)
        self._data = data
        self._lock = lock or threading.Lock()

    # ── Construction & loading ────────────────────────────────────────

    @classmethod
    def manifest_path_for(cls, workspace_path: Path | str) -> Path:
        return Path(workspace_path) / MANIFEST_FILENAME

    @property
    def manifest_path(self) -> Path:
        return self.manifest_path_for(self.workspace_path)

    @classmethod
    def create_from_plan(
        cls,
        workspace_path: Path | str,
        plan_items: Iterable[Any],
        task_id: str | None = None,
    ) -> "ExecutionManifest":
        """Create a fresh manifest with all items in ``pending`` state."""
        now = _now_iso()
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for plan_item in plan_items:
            sample_id, sample_name, platform = _resolve_sample_meta(plan_item)
            if not sample_id or not platform:
                continue
            key = (sample_id, platform)
            if key in seen:
                continue
            seen.add(key)
            items.append(cls._new_item(sample_id, sample_name, platform))

        ws = Path(workspace_path)
        data = {
            "task_id": task_id or ws.name,
            "created_at": now,
            "updated_at": now,
            "items": items,
            "summary": cls._compute_summary(items),
        }
        instance = cls(ws, data)
        instance.save()
        logger.info(
            "Created execution manifest: workspace=%s, items=%d", ws, len(items)
        )
        return instance

    @classmethod
    def load(cls, workspace_path: Path | str) -> "ExecutionManifest | None":
        """Load an existing manifest; return ``None`` if not present."""
        path = cls.manifest_path_for(workspace_path)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load manifest at %s: %s", path, e)
            return None
        if not isinstance(data, dict) or "items" not in data:
            logger.warning("Manifest at %s has unexpected schema; ignoring", path)
            return None
        return cls(workspace_path, data)

    @classmethod
    def load_or_create(
        cls,
        workspace_path: Path | str,
        plan_items: Iterable[Any],
        task_id: str | None = None,
    ) -> "ExecutionManifest":
        """Load existing manifest (merging in any new plan items) or create one."""
        existing = cls.load(workspace_path)
        plan_list = list(plan_items)
        if existing is not None:
            existing.merge_plan(plan_list)
            return existing
        return cls.create_from_plan(workspace_path, plan_list, task_id=task_id)

    # ── Mutators ──────────────────────────────────────────────────────

    def merge_plan(self, plan_items: Iterable[Any]) -> None:
        """Add any plan items missing from the manifest. Existing items kept as-is."""
        added = 0
        with self._lock:
            existing_keys = {
                (it.get("sample_id"), it.get("platform"))
                for it in self._data.get("items", [])
            }
            for plan_item in plan_items:
                try:
                    sample_id, sample_name, platform = _resolve_sample_meta(plan_item)
                except TypeError:
                    continue
                if not sample_id or not platform:
                    continue
                if (sample_id, platform) in existing_keys:
                    continue
                self._data["items"].append(
                    self._new_item(sample_id, sample_name, platform)
                )
                existing_keys.add((sample_id, platform))
                added += 1
            if added:
                self._data["updated_at"] = _now_iso()
                self._data["summary"] = self._compute_summary(self._data["items"])
        if added:
            self.save()
            logger.info("Manifest merged %d new item(s) from plan", added)

    def update_item(
        self,
        sample_id: str,
        platform: str,
        phase: str,
        status: str,
        error: str | None = None,
        pass_rate: float | None = None,
    ) -> None:
        """Update a single phase's status for a (sample_id, platform) item."""
        with self._lock:
            item = self._find_item(sample_id, platform)
            if item is None:
                # Lazy-add: caller may not have been part of original plan.
                item = self._new_item(sample_id, sample_id, platform)
                self._data["items"].append(item)

            phase_data = item["phases"].setdefault(phase, {"status": PHASE_PENDING})
            now = _now_iso()
            phase_data["status"] = status
            if status == PHASE_RUNNING:
                phase_data["started_at"] = now
                # Clear stale terminal markers on retry
                phase_data.pop("completed_at", None)
                phase_data.pop("error", None)
            elif status in (PHASE_COMPLETED, PHASE_FAILED, PHASE_SKIPPED):
                phase_data.setdefault("started_at", now)
                phase_data["completed_at"] = now
            if error is not None:
                phase_data["error"] = str(error)
            elif status == PHASE_COMPLETED:
                phase_data.pop("error", None)
            if pass_rate is not None:
                try:
                    phase_data["pass_rate"] = float(pass_rate)
                except (TypeError, ValueError) as e:
                    logger.debug("pass_rate 转换失败 (value=%r): %s", pass_rate, e)

            # If the item was previously skipped, an explicit phase update revives it.
            if item.get("overall_status") == PHASE_SKIPPED and status != PHASE_SKIPPED:
                # Strip "skipped" marker from sibling phases not explicitly touched.
                for pname, pdata in list(item["phases"].items()):
                    if pname != phase and pdata.get("status") == PHASE_SKIPPED:
                        pdata["status"] = PHASE_PENDING
                        pdata.pop("completed_at", None)

            item["overall_status"] = self._compute_overall_status(item)
            self._data["updated_at"] = now
            self._data["summary"] = self._compute_summary(self._data["items"])
        self.save()

    def mark_as_skipped(self, sample_id: str, platform: str) -> None:
        """Mark an item (and all its phases) as skipped."""
        with self._lock:
            item = self._find_item(sample_id, platform)
            if item is None:
                item = self._new_item(sample_id, sample_id, platform)
                self._data["items"].append(item)
            now = _now_iso()
            for phase_name in PHASES:
                phase_data = item["phases"].setdefault(phase_name, {})
                phase_data["status"] = PHASE_SKIPPED
                phase_data.setdefault("started_at", now)
                phase_data["completed_at"] = now
            item["overall_status"] = PHASE_SKIPPED
            self._data["updated_at"] = now
            self._data["summary"] = self._compute_summary(self._data["items"])
        self.save()

    def force_reset_items(self, pairs: Iterable[tuple[str, str]]) -> int:
        """强制将指定 (sample_id, platform) 项重置为 pending，绕过单调合并。

        ``save()`` 的读-改-写采用 per-phase 单调合并，防止并行进程用陈旧
        快照回退新状态；但 --force 重跑属于有意回退，普通 save() 会把重置
        吞掉（磁盘上的 completed 优先级更高），导致续跑误判样本已完成。
        本方法在文件锁内直接改写磁盘数据并同步内存，确保重置真实落盘。

        Returns:
            实际重置的条目数。
        """
        from ..workspace._safe_io import file_lock as _file_lock

        keys = {(str(s), str(p)) for s, p in pairs}
        if not keys:
            return 0
        path = self.manifest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.parent / ".execution_manifest.lock"
        now = _now_iso()
        reset_count = 0
        with self._lock:
            with _file_lock(lock_path):
                # 以磁盘最新状态为基准（其他进程可能已更新），读失败时退回内存版本
                base: dict[str, Any] = self._data
                if path.exists():
                    try:
                        loaded = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict) and loaded.get("items"):
                            base = loaded
                    except (OSError, json.JSONDecodeError) as e:
                        logger.warning("manifest read failed during force reset: %s", e)
                for it in base.get("items", []):
                    if (it.get("sample_id", ""), it.get("platform", "")) in keys:
                        it["phases"] = {}
                        it["overall_status"] = PHASE_PENDING
                        reset_count += 1
                base["updated_at"] = now
                base["summary"] = self._compute_summary(base.get("items", []))
                self._write_json_atomic(path, base)
                # 内存同步为重置后的版本，后续 update_item 以此为基线
                self._data = base
        if reset_count:
            logger.info("Manifest force-reset %d item(s) to pending", reset_count)
        return reset_count

    def recover_stuck_running_items(
        self,
        timeout_seconds: int = 3600,
        platforms: set[str] | None = None,
        phases: set[str] | None = None,
    ) -> tuple[int, list[tuple[str, str, str]]]:
        """恢复超时未完成的 PHASE_RUNNING 项。

        如果一个项在 PHASE_RUNNING 状态超过 timeout_seconds，
        表示执行进程已经死亡或卡死，需要标记为失败并允许重试。

        Args:
            timeout_seconds: 判断为"超时"的阈值（默认 1 小时）
            platforms: 当前执行计划涉及的平台集合；为 None 时恢复所有平台，
                否则仅恢复属于该集合的任务（避免恢复不相关平台的历史卡住任务）
            phases: 限定恢复的阶段集合（如 {"evaluate"}）；为 None 时恢复所有阶段。
                流水线模式下 generate/evaluate 进程并行，evaluate 进程必须限定
                phases={"evaluate"}，避免把正在生成中的样本误标为失败

        Returns:
            (recovered_count, recovered_items_list)
            其中 recovered_items_list = [(sample_id, platform, phase), ...]
        """
        recovered_items: list[tuple[str, str, str]] = []
        now = _now_iso()
        now_dt = datetime.now()

        with self._lock:
            for item in self._data.get("items", []):
                # 平台过滤：仅处理当前执行计划中涉及的平台
                if platforms and item.get("platform") not in platforms:
                    continue
                for phase_name, phase_data in item.get("phases", {}).items():
                    if phases and phase_name not in phases:
                        continue
                    if phase_data.get("status") != PHASE_RUNNING:
                        continue
                    started_at = phase_data.get("started_at")
                    if not started_at:
                        continue
                    try:
                        started_dt = datetime.fromisoformat(started_at)
                    except (ValueError, TypeError):
                        continue
                    elapsed = (now_dt - started_dt).total_seconds()
                    if elapsed < timeout_seconds:
                        continue

                    # Mark as failed
                    phase_data["status"] = PHASE_FAILED
                    if not phase_data.get("error"):
                        phase_data["error"] = (
                            f"Recovered from PHASE_RUNNING"
                            f" (timeout after {int(elapsed)}s)"
                        )
                    phase_data["completed_at"] = now
                    phase_data["recovered_from_running"] = True

                    # Recalculate overall_status for the item
                    item["overall_status"] = self._compute_overall_status(item)

                    recovered_items.append(
                        (item.get("sample_id", ""), item.get("platform", ""), phase_name)
                    )

            if recovered_items:
                self._data["updated_at"] = now
                self._data["summary"] = self._compute_summary(self._data["items"])

        if recovered_items:
            self.save()
            logger.info(
                "Recovered %d stuck running item(s): %s",
                len(recovered_items),
                recovered_items,
            )

        return len(recovered_items), recovered_items

    # ── Queries ───────────────────────────────────────────────────────

    def get_pending_items(self) -> list[dict[str, Any]]:
        """Return items that still need work (pending / failed / running)."""
        with self._lock:
            return [
                dict(it)
                for it in self._data.get("items", [])
                if it.get("overall_status") in (PHASE_PENDING, PHASE_FAILED, PHASE_RUNNING)
            ]

    def get_completed_items(self) -> list[dict[str, Any]]:
        """Return items whose overall status is completed."""
        with self._lock:
            return [
                dict(it)
                for it in self._data.get("items", [])
                if it.get("overall_status") == PHASE_COMPLETED
            ]

    def is_phase_completed(self, sample_id: str, platform: str, phase: str) -> bool:
        with self._lock:
            item = self._find_item(sample_id, platform)
            if not item:
                return False
            return item.get("phases", {}).get(phase, {}).get("status") == PHASE_COMPLETED

    def get_phase_status(self, sample_id: str, platform: str, phase: str) -> str:
        with self._lock:
            item = self._find_item(sample_id, platform)
            if not item:
                return PHASE_PENDING
            return item.get("phases", {}).get(phase, {}).get("status", PHASE_PENDING)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data, default=str))

    # ── Persistence ───────────────────────────────────────────────────

    def save(self) -> None:
        """Persist manifest to disk with cross-process file lock + merge.

        多个 evalapp evaluate 子进程并行写同一工作区的 manifest 时，
        简单 atomic write 会导致后写的进程覆盖先写进程的更新。
        此方法在文件锁保护下执行「读-改-写」：
        1. 获取文件锁（fcntl.flock，跨进程互斥）
        2. 读取磁盘上最新的 manifest（其他进程可能已更新它）
        3. 将本进程内存中的 item 状态合并进去（per-item 粒度，只更新本进程写过的条目）
        4. 原子写入合并后的结果
        """
        from ..workspace._safe_io import file_lock as _file_lock

        path = self.manifest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.parent / ".execution_manifest.lock"

        with self._lock:
            # 取内存中所有 item 的快照（key → item dict）
            my_items: dict[tuple[str, str], dict[str, Any]] = {
                (it.get("sample_id", ""), it.get("platform", "")): it
                for it in self._data.get("items", [])
            }
            my_meta = {
                k: v for k, v in self._data.items() if k != "items"
            }

        with _file_lock(lock_path):
            # 读取磁盘最新状态（其他进程可能已修改）
            disk_data: dict[str, Any] = {}
            if path.exists():
                try:
                    disk_data = json.loads(path.read_text(encoding="utf-8")) or {}
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("manifest read failed during save-merge: %s", e)
                    disk_data = {}
            if not isinstance(disk_data, dict):
                disk_data = {}

            # 以磁盘状态为基础，按 (sample_id, platform) 合并内存更新
            disk_items_map: dict[tuple[str, str], dict[str, Any]] = {}
            for it in disk_data.get("items", []):
                key = (it.get("sample_id", ""), it.get("platform", ""))
                disk_items_map[key] = it

            # 将内存 item 与磁盘 item 做 per-phase 单调合并：
            # 仅当内存 phase 的 status 优先级高于磁盘版本时才覆盖，
            # 避免某个进程用自己的旧内存快照回退另一进程已写入的更新。
            for key, my_item in my_items.items():
                disk_items_map[key] = _merge_item(my_item, disk_items_map.get(key))

            merged_items = list(disk_items_map.values())

            # 合并顶层元数据（内存版本优先，但保留磁盘中已有的 created_at）
            merged = {**disk_data, **my_meta}
            merged["items"] = merged_items
            merged["updated_at"] = _now_iso()
            merged["summary"] = self._compute_summary(merged_items)

            self._write_json_atomic(path, merged)

    @staticmethod
    def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
        """原子写入 JSON：同目录临时文件 + os.replace。"""
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError as e:
                    logger.debug("fsync 失败（仅影响耐久性保证）: %s", e)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError as e:
                logger.debug("删除临时 manifest 失败 (path=%s): %s", tmp_name, e)
            raise

    # ── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _new_item(sample_id: str, sample_name: str, platform: str) -> dict[str, Any]:
        return {
            "sample_id": sample_id,
            "sample_name": sample_name or sample_id,
            "platform": platform,
            "phases": {},
            "overall_status": PHASE_PENDING,
        }

    def _find_item(self, sample_id: str, platform: str) -> dict[str, Any] | None:
        for item in self._data.get("items", []):
            if item.get("sample_id") == sample_id and item.get("platform") == platform:
                return item
        return None

    @staticmethod
    def _compute_overall_status(item: dict[str, Any]) -> str:
        phases = item.get("phases", {})
        if not phases:
            return PHASE_PENDING
        statuses = [p.get("status", PHASE_PENDING) for p in phases.values()]
        if any(s == PHASE_FAILED for s in statuses):
            return PHASE_FAILED
        if any(s == PHASE_RUNNING for s in statuses):
            return PHASE_RUNNING
        # All declared phases must be completed for the item to be considered completed.
        if all(s == PHASE_COMPLETED for s in statuses) and all(
            p in phases for p in PHASES
        ):
            return PHASE_COMPLETED
        # Treat fully-skipped item as skipped (rare path; mark_as_skipped handles it).
        if all(s == PHASE_SKIPPED for s in statuses) and statuses:
            return PHASE_SKIPPED
        return PHASE_PENDING

    @staticmethod
    def _compute_summary(items: list[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "total": len(items),
            "completed": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "skipped": 0,
        }
        for it in items:
            st = it.get("overall_status", PHASE_PENDING)
            if st in summary:
                summary[st] += 1
            else:
                summary["pending"] += 1
        return summary


__all__ = [
    "ExecutionManifest",
    "ManifestItem",
    "MANIFEST_FILENAME",
    "PHASES",
    "PHASE_PENDING",
    "PHASE_RUNNING",
    "PHASE_COMPLETED",
    "PHASE_FAILED",
    "PHASE_SKIPPED",
]
