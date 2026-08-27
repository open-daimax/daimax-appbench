"""Tests for evalapp/execution_manifest.py — ExecutionManifest.

覆盖:
- recover_stuck_running_items 超时恢复逻辑
- 未超时项不受影响
- 保留已有 error 字段
- summary 重新计算
- 幂等性验证
- force_reset_items 穿透单调合并的强制重置
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


from evalapp.evaluation.execution_manifest import (
    ExecutionManifest,
    PHASE_COMPLETED,
    PHASE_FAILED,
    PHASE_PENDING,
    PHASE_RUNNING,
)


def _make_manifest(tmp_path: Path, items: list[dict]) -> ExecutionManifest:
    """Helper: construct ExecutionManifest from item list with manual data."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    data = {
        "task_id": "test-task",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "summary": ExecutionManifest._compute_summary(items),
    }
    return ExecutionManifest(workspace, data)


def _make_item(sample_id: str, platform: str, phases: dict) -> dict:
    """Create a manifest item with given phases.

    phases: dict mapping phase_name -> dict of phase attributes
    """
    item = {
        "sample_id": sample_id,
        "sample_name": sample_id,
        "platform": platform,
        "phases": {},
        "overall_status": PHASE_PENDING,
    }
    for phase_name, attrs in phases.items():
        item["phases"][phase_name] = dict(attrs)
    item["overall_status"] = ExecutionManifest._compute_overall_status(item)
    return item


class TestRecoverStuckRunningItems:
    """Tests for ExecutionManifest.recover_stuck_running_items."""

    def test_recover_stuck_running_items_timeout(self, tmp_path: Path):
        """超时的 PHASE_RUNNING 项被正确恢复为 PHASE_FAILED."""
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        items = [
            _make_item("s1", "ios", {
                "generate": {"status": PHASE_RUNNING, "started_at": two_hours_ago}
            })
        ]
        manifest = _make_manifest(tmp_path, items)

        count, recovered = manifest.recover_stuck_running_items(timeout_seconds=3600)

        assert count == 1
        assert recovered == [("s1", "ios", "generate")]

        phase = manifest._data["items"][0]["phases"]["generate"]
        assert phase["status"] == PHASE_FAILED
        assert "Recovered" in phase["error"]
        assert phase["recovered_from_running"] is True
        assert "completed_at" in phase

    def test_recover_stuck_running_items_not_timeout(self, tmp_path: Path):
        """未超时的 PHASE_RUNNING 项不受影响."""
        ten_mins_ago = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
        items = [
            _make_item("s1", "ios", {
                "generate": {"status": PHASE_RUNNING, "started_at": ten_mins_ago}
            })
        ]
        manifest = _make_manifest(tmp_path, items)

        count, recovered = manifest.recover_stuck_running_items(timeout_seconds=3600)

        assert count == 0
        assert recovered == []

        phase = manifest._data["items"][0]["phases"]["generate"]
        assert phase["status"] == PHASE_RUNNING
        assert "error" not in phase
        assert "recovered_from_running" not in phase

    def test_recover_stuck_running_items_preserves_existing_error(self, tmp_path: Path):
        """恢复超时的 RUNNING 项时，保留原始 error 字段不被覆盖."""
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        items = [
            _make_item("s1", "ios", {
                "generate": {
                    "status": PHASE_RUNNING,
                    "started_at": two_hours_ago,
                    "error": "Original error message",
                }
            })
        ]
        manifest = _make_manifest(tmp_path, items)

        count, recovered = manifest.recover_stuck_running_items(timeout_seconds=3600)

        assert count == 1
        phase = manifest._data["items"][0]["phases"]["generate"]
        assert phase["status"] == PHASE_FAILED
        assert phase["error"] == "Original error message"
        assert "Recovered" not in phase["error"]
        assert phase["recovered_from_running"] is True

    def test_recover_stuck_running_items_summary_updated(self, tmp_path: Path):
        """恢复后 summary 中 running 数减少、failed 数增加."""
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        ten_mins_ago = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")

        items = [
            _make_item("s1", "ios", {
                "generate": {"status": PHASE_RUNNING, "started_at": two_hours_ago}
            }),
            _make_item("s2", "android", {
                "generate": {"status": PHASE_RUNNING, "started_at": ten_mins_ago}
            }),
            _make_item("s3", "ios", {
                "generate": {"status": PHASE_COMPLETED},
                "evaluate": {"status": PHASE_COMPLETED},
            }),
            _make_item("s4", "android", {
                "generate": {"status": PHASE_COMPLETED},
                "evaluate": {"status": PHASE_COMPLETED},
            }),
        ]
        manifest = _make_manifest(tmp_path, items)
        old_summary = dict(manifest._data["summary"])

        count, recovered = manifest.recover_stuck_running_items(timeout_seconds=3600)

        assert count == 1
        new_summary = manifest._data["summary"]
        assert new_summary["running"] == old_summary["running"] - 1
        assert new_summary["failed"] == old_summary["failed"] + 1
        assert new_summary["completed"] == old_summary["completed"]

    def test_recover_stuck_running_items_idempotent(self, tmp_path: Path):
        """连续调用两次 recover_stuck_running_items，第二次返回 (0, [])."""
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        items = [
            _make_item("s1", "ios", {
                "generate": {"status": PHASE_RUNNING, "started_at": two_hours_ago}
            })
        ]
        manifest = _make_manifest(tmp_path, items)

        count1, recovered1 = manifest.recover_stuck_running_items(timeout_seconds=3600)
        assert count1 == 1
        assert len(recovered1) == 1

        count2, recovered2 = manifest.recover_stuck_running_items(timeout_seconds=3600)
        assert count2 == 0
        assert recovered2 == []


class TestForceResetItems:
    """Tests for ExecutionManifest.force_reset_items（--force 重跑的强制重置）."""

    def _completed_item(self, sample_id: str, platform: str) -> dict:
        return _make_item(sample_id, platform, {
            "generate": {"status": PHASE_COMPLETED, "started_at": "2026-08-04T21:20:37",
                         "completed_at": "2026-08-04T22:43:32"},
            "evaluate": {"status": PHASE_COMPLETED, "started_at": "2026-08-04T22:43:39",
                         "completed_at": "2026-08-05T02:51:39"},
        })

    def test_force_reset_persists_to_disk(self, tmp_path: Path):
        """重置必须真实落盘：磁盘上 completed 状态被清空，不被单调合并吃掉."""
        items = [self._completed_item("s1", "expo_web"),
                 self._completed_item("s2", "expo_web")]
        manifest = _make_manifest(tmp_path, items)
        manifest.save()  # 磁盘上已有 completed 状态

        count = manifest.force_reset_items([("s1", "expo_web")])
        assert count == 1

        reloaded = ExecutionManifest.load(manifest.workspace_path)
        assert reloaded is not None
        s1 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s1")
        s2 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s2")
        assert s1["phases"] == {}
        assert s1["overall_status"] == PHASE_PENDING
        # 未指定的项不受影响
        assert s2["phases"]["generate"]["status"] == PHASE_COMPLETED
        assert s2["overall_status"] == PHASE_COMPLETED
        # summary 同步重算
        assert reloaded._data["summary"]["pending"] == 1
        assert reloaded._data["summary"]["completed"] == 1

    def test_update_after_force_reset_writes_fresh_state(self, tmp_path: Path):
        """重置后 update_item 能正常写入新状态（running 不再被旧 completed 压制）."""
        items = [self._completed_item("s1", "expo_web")]
        manifest = _make_manifest(tmp_path, items)
        manifest.save()

        manifest.force_reset_items([("s1", "expo_web")])
        manifest.update_item("s1", "expo_web", "generate", PHASE_RUNNING)

        reloaded = ExecutionManifest.load(manifest.workspace_path)
        s1 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s1")
        assert s1["phases"]["generate"]["status"] == PHASE_RUNNING
        # 旧的 8-04 时间戳已被清除，重新开始计时
        assert s1["phases"]["generate"]["started_at"] != "2026-08-04T21:20:37"
        # evaluate phase 不应残留旧 completed 状态
        assert "evaluate" not in s1["phases"]

    def test_force_reset_empty_pairs_noop(self, tmp_path: Path):
        """空 pairs 直接返回 0，不碰磁盘."""
        items = [self._completed_item("s1", "expo_web")]
        manifest = _make_manifest(tmp_path, items)
        manifest.save()

        assert manifest.force_reset_items([]) == 0

        reloaded = ExecutionManifest.load(manifest.workspace_path)
        s1 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s1")
        assert s1["phases"]["generate"]["status"] == PHASE_COMPLETED

    def test_force_reset_unknown_pair_returns_zero(self, tmp_path: Path):
        """目标项不存在时返回 0，其他项不受影响."""
        items = [self._completed_item("s1", "expo_web")]
        manifest = _make_manifest(tmp_path, items)
        manifest.save()

        assert manifest.force_reset_items([("nope", "expo_web")]) == 0

        reloaded = ExecutionManifest.load(manifest.workspace_path)
        s1 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s1")
        assert s1["phases"]["generate"]["status"] == PHASE_COMPLETED

    def test_force_reset_merges_latest_disk_state(self, tmp_path: Path):
        """重置以磁盘最新状态为基准：其他进程新写的项不丢失."""
        items = [self._completed_item("s1", "expo_web")]
        manifest = _make_manifest(tmp_path, items)
        manifest.save()

        # 模拟另一进程在磁盘上新增了 s2
        other = ExecutionManifest.load(manifest.workspace_path)
        other.update_item("s2", "expo_web", "generate", PHASE_COMPLETED)

        manifest.force_reset_items([("s1", "expo_web")])

        reloaded = ExecutionManifest.load(manifest.workspace_path)
        ids = {it["sample_id"] for it in reloaded._data["items"]}
        assert ids == {"s1", "s2"}
        s1 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s1")
        s2 = next(it for it in reloaded._data["items"] if it["sample_id"] == "s2")
        assert s1["overall_status"] == PHASE_PENDING
        assert s2["phases"]["generate"]["status"] == PHASE_COMPLETED
