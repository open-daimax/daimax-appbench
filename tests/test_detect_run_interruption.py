"""detect_run_interruption 重设计的回归测试。

覆盖判据三态与辅助保证：
* 全 completed + 最新 evaluate run 已 finish → interrupted=False
* running > 0（存在未终结项）→ interrupted=True
* completed + failed == total 且 running=0（失败样本属正常终结）→ False
* report run 未 finish 但 evaluate run 已 finish → False（跳过 report 阶段 run）
* completed_samples / total_samples 为去重样本数（items 是样本×平台 pair）
* command.json 缺失/损坏不抛出
* _resolve_latest_run_dir 的 report 跳过与 exclude_run_dir 双保险
* 新鲜度仲裁平局（同事件时间戳相等）一律选 scores.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from evalapp.services.report_backfill import (
    _resolve_latest_run_dir,
    detect_run_interruption,
)


# ====================== 构造辅助 ======================


def _write_manifest(
    workspace: Path,
    summary: dict,
    items: list[dict],
) -> None:
    (workspace / "execution_manifest.json").write_text(
        json.dumps({"summary": summary, "items": items}),
        encoding="utf-8",
    )


def _item(sample_id: str, platform: str, status: str) -> dict:
    return {
        "sample_id": sample_id,
        "platform": platform,
        "overall_status": status,
    }


def _make_run(
    workspace: Path,
    name: str,
    phase: str,
    *,
    finished: bool = True,
    with_result_summary: bool = True,
    command_content: str | None = None,
    link_latest: bool = False,
) -> Path:
    run_dir = workspace / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "phase").write_text(phase, encoding="utf-8")
    if command_content is not None:
        (run_dir / "command.json").write_text(command_content, encoding="utf-8")
    else:
        cmd = {
            "command": f"evalapp {phase}",
            "started_at": "2026-09-17T11:22:42.000000",
            "finished_at": "2026-09-17T13:35:43.000000" if finished else None,
        }
        (run_dir / "command.json").write_text(
            json.dumps(cmd), encoding="utf-8",
        )
    if with_result_summary:
        (run_dir / "result_summary.json").write_text("{}", encoding="utf-8")
    if link_latest:
        latest = workspace / "runs" / "latest"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        os.symlink(name, latest)
    return run_dir


def _summary_of(items: list[dict]) -> dict:
    summary = {
        "total": len(items), "completed": 0, "failed": 0,
        "running": 0, "pending": 0, "skipped": 0,
    }
    for it in items:
        summary[it["overall_status"]] += 1
    return summary


# ====================== 判据三态 ======================


class TestDetectRunInterruption:
    def test_all_completed_and_latest_evaluate_run_finished(self, tmp_path: Path):
        """全 completed + 最新 evaluate run 已 finish → False。"""
        items = [_item(f"s{i}", "expo_web", "completed") for i in range(3)]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(tmp_path, "20260910_212250", "evaluate", link_latest=True)

        result = detect_run_interruption(tmp_path)

        assert result == {
            "interrupted": False, "completed_samples": 3, "total_samples": 3,
        }

    def test_running_items_mark_interrupted(self, tmp_path: Path):
        """running > 0（存在未终结项）→ True。"""
        items = [
            _item("s0", "expo_web", "completed"),
            _item("s1", "expo_web", "running"),
            _item("s2", "expo_web", "pending"),
        ]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(tmp_path, "20260910_212250", "evaluate", link_latest=True)

        result = detect_run_interruption(tmp_path)

        assert result["interrupted"] is True
        # 去重样本数：completed 1 / 总 3
        assert result["completed_samples"] == 1
        assert result["total_samples"] == 3

    def test_completed_plus_failed_equals_total_is_not_interrupted(self, tmp_path: Path):
        """completed + failed == total 且 running=0 → False（失败属正常终结）。"""
        items = [_item("s0", "expo_web", "completed")] + [
            _item(f"s{i}", "expo_web", "failed") for i in range(1, 34)
        ]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(tmp_path, "20260917_112242", "evaluate", link_latest=True)

        result = detect_run_interruption(tmp_path)

        assert result["interrupted"] is False
        assert result["completed_samples"] == 1
        assert result["total_samples"] == 34

    def test_unfinished_evaluate_run_marks_interrupted(self, tmp_path: Path):
        """最新 evaluate run 未 finish（finished_at=null）→ True。"""
        items = [_item("s0", "expo_web", "completed")]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(
            tmp_path, "20260917_151323", "evaluate",
            finished=False, with_result_summary=False, link_latest=True,
        )

        result = detect_run_interruption(tmp_path)

        assert result["interrupted"] is True

    def test_report_run_unfinished_but_evaluate_finished(self, tmp_path: Path):
        """report run 未 finish 但 evaluate run 已 finish → False。

        report 阶段自己创建的 run 在执行期间必然 finished_at=null，
        必须被跳过，否则 interrupted 恒真。
        """
        items = [_item(f"s{i}", "expo_web", "completed") for i in range(3)]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(tmp_path, "20260910_212250", "evaluate")
        # 最新 run 是 report 阶段，未收尾，且 runs/latest 指向它
        _make_run(
            tmp_path, "20260911_033823", "report",
            finished=False, with_result_summary=False, link_latest=True,
        )

        result = detect_run_interruption(tmp_path)

        assert result["interrupted"] is False


# ====================== 去重样本数 ======================


class TestSampleDedup:
    def test_multi_platform_items_dedup_by_sample_id(self, tmp_path: Path):
        """items 为样本×平台 pair，completed/total_samples 按 sample_id 去重。"""
        items = [
            _item("s0", "expo_web", "completed"),
            _item("s0", "expo_android", "completed"),
            _item("s1", "expo_web", "completed"),
            _item("s1", "expo_android", "failed"),
            _item("s2", "expo_web", "failed"),
            _item("s2", "expo_android", "failed"),
        ]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(tmp_path, "20260910_212250", "evaluate", link_latest=True)

        result = detect_run_interruption(tmp_path)

        assert result["interrupted"] is False
        assert result["total_samples"] == 3
        # s0 双平台 completed，s1 仅一个平台 completed → 去重后 2
        assert result["completed_samples"] == 2


# ====================== 健壮性：永不抛出 ======================


class TestRobustness:
    def test_missing_manifest_and_runs(self, tmp_path: Path):
        """无 manifest、无 runs → 全 0，不抛出。"""
        result = detect_run_interruption(tmp_path)
        assert result == {
            "interrupted": False, "completed_samples": 0, "total_samples": 0,
        }

    def test_corrupt_manifest_does_not_raise(self, tmp_path: Path):
        """manifest 损坏 → 三字段仍写出（0 值），不抛出。"""
        (tmp_path / "execution_manifest.json").write_text(
            "{not json", encoding="utf-8",
        )
        result = detect_run_interruption(tmp_path)
        assert result["interrupted"] is False
        assert result["completed_samples"] == 0
        assert result["total_samples"] == 0

    def test_missing_command_json_does_not_raise(self, tmp_path: Path):
        """command.json 缺失 → 辅判据不抛出（缺 result_summary 仍判 True）。"""
        items = [_item("s0", "expo_web", "completed")]
        _write_manifest(tmp_path, _summary_of(items), items)
        run_dir = _make_run(tmp_path, "20260910_212250", "evaluate", link_latest=True)
        (run_dir / "command.json").unlink()

        result = detect_run_interruption(tmp_path)

        assert isinstance(result["interrupted"], bool)

    def test_corrupt_command_json_does_not_raise(self, tmp_path: Path):
        """command.json 解析失败 → 降级跳过该判据，不抛出、不误判。"""
        items = [_item("s0", "expo_web", "completed")]
        _write_manifest(tmp_path, _summary_of(items), items)
        _make_run(
            tmp_path, "20260910_212250", "evaluate",
            command_content="{broken", link_latest=True,
        )

        result = detect_run_interruption(tmp_path)

        assert result["interrupted"] is False


# ====================== _resolve_latest_run_dir ======================


class TestResolveLatestRunDir:
    def test_skips_report_phase_runs(self, tmp_path: Path):
        _make_run(tmp_path, "20260910_212250", "evaluate")
        report_run = _make_run(
            tmp_path, "20260911_033823", "report",
            finished=False, link_latest=True,
        )

        resolved = _resolve_latest_run_dir(tmp_path)

        assert resolved is not None
        assert resolved.name == "20260910_212250"
        assert resolved != report_run.resolve()

    def test_exclude_run_dir_double_insurance(self, tmp_path: Path):
        """exclude_run_dir 排除最新 evaluate run 后回退到更早的 run。"""
        older = _make_run(tmp_path, "20260910_212250", "evaluate")
        newer = _make_run(tmp_path, "20260917_151323", "evaluate", link_latest=True)

        resolved = _resolve_latest_run_dir(tmp_path, exclude_run_dir=newer)

        assert resolved == older

    def test_no_runs_returns_none(self, tmp_path: Path):
        assert _resolve_latest_run_dir(tmp_path) is None

    def test_only_report_runs_returns_none(self, tmp_path: Path):
        _make_run(tmp_path, "20260911_033823", "report", link_latest=True)
        assert _resolve_latest_run_dir(tmp_path) is None


# ====================== 新鲜度仲裁平局 ======================


class TestFreshnessTieBreak:
    """同事件写入（updated_at 严格相等）一律选信息更完整的 scores.json。"""

    @staticmethod
    def _write_pair(sample_dir: Path, scores_ts: str, ss_ts: str) -> None:
        sample_dir.mkdir(parents=True, exist_ok=True)
        (sample_dir / "scores.json").write_text(json.dumps({
            "sample_id": "s0",
            "updated_at": scores_ts,
            "platforms": {"expo_web": {
                "success_rate_score": 100.0,
                "backend_completeness": 80.0,
            }},
        }), encoding="utf-8")
        # 人为制造 sample_scores.json 的 mtime 更新（跨秒边界的写盘顺序场景）
        (sample_dir / "sample_scores.json").write_text(json.dumps({
            "sample_id": "s0",
            "updated_at": ss_ts,
            "platforms": {"expo_web": {
                "platform": "expo_web",
                "updated_at": ss_ts,
                "scores": {"success_rate": 100.0},
            }},
        }), encoding="utf-8")
        os.utime(sample_dir / "sample_scores.json", (2e9, 2e9))

    def test_equal_timestamps_selects_scores_json(self, tmp_path: Path):
        from evalapp.services.report_aggregator import _resolve_fresh_scores

        sample_dir = tmp_path / "s0"
        self._write_pair(sample_dir, "2026-09-17T12:00:00", "2026-09-17T12:00:00")

        raw, source = _resolve_fresh_scores(sample_dir)

        assert source == "scores"
        # scores.json 独有字段未丢失
        assert raw["platforms"]["expo_web"]["backend_completeness"] == 80.0

    def test_strictly_newer_sample_scores_still_wins(self, tmp_path: Path):
        from evalapp.services.report_aggregator import _resolve_fresh_scores

        sample_dir = tmp_path / "s0"
        self._write_pair(sample_dir, "2026-09-17T12:00:00", "2026-09-17T12:00:01")

        _raw, source = _resolve_fresh_scores(sample_dir)

        assert source == "sample_scores"
