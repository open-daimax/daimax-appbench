"""报告目录数据管理。

修复要点：
* ``write_scores_summary`` 与 ``write_stability`` 改为原子写入，避免覆盖型写入
  在并发或崩溃场景下产生半截文件（W-09）。
* ``write_scores_summary`` 在工作区级别加文件锁，防止同一工作区多个评测任务
  并行 reporting 时互相覆盖。
* ``write_stability`` 按 ``sample_id`` 分目录，自带隔离，仅需保证原子写入。
"""
import json
from pathlib import Path

from ..utils.files import round_scores
from ._safe_io import atomic_write_json, file_lock

SCORES_SUMMARY_LOCK = ".scores_summary.lock"


def write_scores_summary(workspace_dir: Path, data: dict):
    """写入 report/scores_summary.json（原子写入 + 工作区锁）。"""
    workspace_dir = Path(workspace_dir)
    report_dir = workspace_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    data = round_scores(data)
    with file_lock(workspace_dir / SCORES_SUMMARY_LOCK):
        atomic_write_json(report_dir / "scores_summary.json", data)


def read_scores_summary(workspace_dir: Path) -> dict | None:
    """读取 report/scores_summary.json（在工作区锁内读取，避免读到半截写入）。"""
    workspace_dir = Path(workspace_dir)
    path = workspace_dir / "report" / "scores_summary.json"
    if not path.exists():
        return None
    # 与 write_scores_summary 共用同一把工作区锁，确保读到的是完整快照
    with file_lock(workspace_dir / SCORES_SUMMARY_LOCK):
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def write_stability(workspace_dir: Path, sample_id: str, data: dict):
    """写入 report/stability/{sample_id}/crash_anr_events.json（原子写入）。"""
    workspace_dir = Path(workspace_dir)
    stability_dir = workspace_dir / "report" / "stability" / sample_id
    stability_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(stability_dir / "crash_anr_events.json", data)
