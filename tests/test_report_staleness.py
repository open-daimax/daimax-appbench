"""Tests for stale e2e report detection and blocking.

Covers the defect where a failed case (timeout/no own report) reused
the previous case's leftover HTML from the shared midscene_run/report/
directory, including the ``mtime == started_at`` edge case where mtime
tolerance alone cannot flag staleness.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from evalapp.evaluation.results.models import EvalRun, PromptResult, TestCaseResult
from evalapp.evaluation.results.store import ResultStore
from evalapp.evaluation.runner.test_phase import (
    _parse_report_filename_timestamp,
    recover_timeout_artifacts,
    snapshot_report,
)


def _playwright_name(dt: datetime, suffix: str = "abcd") -> str:
    return f"playwright-{dt.strftime('%Y-%m-%d_%H-%M-%S')}-{suffix}.html"


class TestFilenameTimestampParsing:
    def test_parse_valid_name(self):
        ts = _parse_report_filename_timestamp(
            "playwright-2026-08-04_23-40-08-xxxx.html"
        )
        assert ts == datetime(2026, 8, 4, 23, 40, 8).timestamp()

    def test_parse_failure_returns_none(self):
        assert _parse_report_filename_timestamp("report.html") is None
        assert _parse_report_filename_timestamp(
            "playwright-not-a-timestamp.html"
        ) is None


class TestSnapshotReportStaleBlocking:
    def test_stale_mtime_blocks_snapshot(self, tmp_path: Path):
        src = tmp_path / "report.html"
        src.write_text("<html>old</html>")
        started_at = time.time()
        old = started_at - 300
        os.utime(src, (old, old))

        path, generated_at = snapshot_report(
            raw_report_path=str(src),
            test_case_id="TC001",
            platform="expo_web",
            started_at=started_at,
            reports_cache_root=tmp_path / "cache",
        )
        assert path == ""
        assert generated_at == 0.0
        assert not (tmp_path / "cache").exists()

    def test_stale_filename_blocks_when_mtime_equals_start(self, tmp_path: Path):
        # Edge case (FlashSale/AquariumManager): stale file's mtime is
        # exactly the failed case's started_at, so the 5s mtime
        # tolerance never triggers — the filename timestamp must catch it.
        started_at = time.time()
        old_dt = datetime.fromtimestamp(started_at) - timedelta(minutes=10)
        src = tmp_path / _playwright_name(old_dt)
        src.write_text("<html>stale</html>")
        os.utime(src, (started_at, started_at))

        path, generated_at = snapshot_report(
            raw_report_path=str(src),
            test_case_id="TC001",
            platform="expo_web",
            started_at=started_at,
            reports_cache_root=tmp_path / "cache",
        )
        assert path == ""
        assert generated_at == 0.0

    def test_fresh_report_with_unparsable_name_is_snapshotted(self, tmp_path: Path):
        # Zero-false-positive line: an unparsable filename must not
        # trigger the filename-based check; fresh mtime → snapshot.
        started_at = time.time()
        src = tmp_path / "report.html"
        src.write_text("<html>fresh</html>")

        path, generated_at = snapshot_report(
            raw_report_path=str(src),
            test_case_id="TC001",
            platform="expo_web",
            started_at=started_at,
            reports_cache_root=tmp_path / "cache",
        )
        assert path != ""
        assert Path(path).exists()
        assert generated_at > 0.0

    def test_fresh_playwright_name_is_snapshotted(self, tmp_path: Path):
        started_at = time.time()
        src = tmp_path / _playwright_name(datetime.fromtimestamp(started_at))
        src.write_text("<html>fresh</html>")

        path, _ = snapshot_report(
            raw_report_path=str(src),
            test_case_id="TC001",
            platform="expo_web",
            started_at=started_at,
            reports_cache_root=tmp_path / "cache",
        )
        assert path != ""


class TestRecoverTimeoutArtifacts:
    def test_stale_filename_candidate_dropped_no_fallback(self, tmp_path: Path):
        # Stale file with mtime touched to started_at: mtime gate
        # passes, filename timestamp must drop it; no fallback.
        started_at = time.time()
        old_dt = datetime.fromtimestamp(started_at) - timedelta(minutes=10)
        stale = tmp_path / "midscene_run" / "report" / _playwright_name(old_dt)
        stale.parent.mkdir(parents=True)
        stale.write_text("<html>stale</html>")
        os.utime(stale, (started_at, started_at))

        report_path, diagnostics = recover_timeout_artifacts(
            report_dir=tmp_path,
            test_case_id="TC001",
            started_at=started_at,
        )
        assert report_path == ""
        assert diagnostics is None

    def test_case_token_candidate_preferred(self, tmp_path: Path):
        started_at = time.time()
        report_root = tmp_path / "midscene_run" / "report"
        report_root.mkdir(parents=True)
        now_dt = datetime.fromtimestamp(started_at)
        other = report_root / _playwright_name(now_dt, "other")
        other.write_text("<html>other</html>")
        mine = report_root / f"playwright-TC001-{now_dt.strftime('%Y-%m-%d_%H-%M-%S')}.html"
        mine.write_text("<html>mine</html>")

        report_path, _ = recover_timeout_artifacts(
            report_dir=tmp_path,
            test_case_id="TC001",
            started_at=started_at,
        )
        assert report_path == str(mine)

    def test_fresh_candidate_still_recovered(self, tmp_path: Path):
        started_at = time.time()
        report_root = tmp_path / "midscene_run" / "report"
        report_root.mkdir(parents=True)
        fresh = report_root / _playwright_name(datetime.fromtimestamp(started_at))
        fresh.write_text("<html>fresh</html>")

        report_path, _ = recover_timeout_artifacts(
            report_dir=tmp_path,
            test_case_id="TC001",
            started_at=started_at,
        )
        assert report_path == str(fresh)


class TestStoreStaleExport:
    def _make_run(self, report_file: Path, *, started_at: float, generated_at: float) -> EvalRun:
        tr = TestCaseResult(
            test_case_id="TC001",
            passed=False,
            status="FAIL",
            report_path=str(report_file),
            report_started_at=started_at,
            report_generated_at=generated_at,
        )
        pr = PromptResult(
            prompt_id="p1",
            sample_id="SampleA",
            platform="expo_web",
            generator_name="custom_gen",
            generation_success=True,
            test_results=[tr],
        )
        return EvalRun(run_id="run1", prompt_results=[pr])

    def test_stale_report_exported_but_not_registered(self, tmp_path: Path):
        src = tmp_path / "src" / "report.html"
        src.parent.mkdir()
        src.write_text("<html>stale</html>")
        started_at = time.time()
        run = self._make_run(
            src, started_at=started_at, generated_at=started_at - 300,
        )
        store = ResultStore(tmp_path / "results")
        output_dir = tmp_path / "out"
        exported = store.export_e2e_reports(run, output_dir)

        # STALE_ file lands on disk for manual review...
        assert len(exported) == 1
        assert exported[0].name.startswith("STALE_")
        # ...but the case's official report_path is cleared, so the
        # frontend renders no "view report" button for it.
        tr = run.prompt_results[0].test_results[0]
        assert tr.report_path == ""
        assert run.prompt_results[0].e2e_report_path == ""

    def test_fresh_report_exported_and_registered(self, tmp_path: Path):
        src = tmp_path / "src" / "report.html"
        src.parent.mkdir()
        src.write_text("<html>fresh</html>")
        started_at = time.time()
        run = self._make_run(
            src, started_at=started_at, generated_at=started_at + 10,
        )
        store = ResultStore(tmp_path / "results")
        output_dir = tmp_path / "out"
        exported = store.export_e2e_reports(run, output_dir)

        assert len(exported) == 1
        assert not exported[0].name.startswith("STALE_")
        tr = run.prompt_results[0].test_results[0]
        assert tr.report_path != ""
        assert run.prompt_results[0].e2e_report_path != ""
