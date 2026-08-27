"""Workspace migrator: migrate old workspace structure to new structure.

修复要点：
* 引入 *staging directory* 模式：先把所有迁移产物写到一个临时兄弟目录，
  全部成功后再 ``os.replace`` 整体重命名为 ``new_workspace``。任何中途失败都
  会清理 staging，保证 ``new_workspace`` 要么完全可用、要么不存在（W-10）。
* 兼容老用法：当传入的 ``new_workspace`` 已存在（半成品恢复），仍按原有逻辑
  增量写入并跳过 staging-rename，避免破坏已有数据。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from ._safe_io import atomic_write_json

logger = get_logger(__name__)


class WorkspaceMigrator:
    """Migrate old workspace structure to new structure.

    Old structure:
    workspace/
    ├── generated_projects/
    │   ├── sample_A/
    │   │   ├── android/
    │   │   └── ios/
    │   └── sample_B/
    ├── e2e_reports/
    │   └── {generator}/
    │       ├── sample_A/
    │       └── sample_B/
    ├── run_data.json
    └── report_data.json

    New structure:
    workspace/
    ├── sample_A/
    │   ├── generated_projects/
    │   │   ├── android/
    │   │   └── ios/
    │   ├── e2e_reports/
    │   │   ├── android/
    │   │   └── ios/
    │   └── sample_report.json
    └── sample_B/
    """

    def __init__(self, old_workspace: Path, new_workspace: Path):
        self.old_workspace = Path(old_workspace)
        self.new_workspace = Path(new_workspace)
        # 运行期目标目录：使用 staging 时指向临时目录，提交后指向最终目录
        self._target: Path = self.new_workspace

    def migrate(self) -> dict[str, Any]:
        """Execute migration with transactional semantics.

        全程使用 staging 目录模式以保证事务性：
        * 始终在 ``new_workspace.parent`` 下创建兄弟临时 staging 目录；
        * 所有迁移产物先写入 staging；
        * 全部成功后用 ``os.replace`` 整体重命名为最终目录；
        * 若 ``new_workspace`` 已存在（半成品续传）则在提交前先整体删除，
          保证 ``new_workspace`` 要么完全可用、要么不存在；
        * 任何中途失败都会清理 staging 目录，避免遗留半成品。

        Returns:
            Migration statistics
        """
        logger.info("Starting workspace migration: %s -> %s", self.old_workspace, self.new_workspace)

        # 1. Load old run data
        # [DEPRECATED] run_data.json 已废弃，此迁移路径将在 v3.0 移除
        run_data_path = self.old_workspace / "run_data.json"
        if not run_data_path.exists():
            logger.error("run_data.json not found in %s", self.old_workspace)
            return {"migrated_samples": [], "failed_samples": [], "total_samples": 0}

        logger.warning(
            "[DEPRECATED] 正在从旧格式 run_data.json 读取迁移数据，"
            "此迁移工具将在 v3.0 移除: %s", run_data_path
        )

        with open(run_data_path, 'r', encoding='utf-8') as f:
            run_data = json.load(f)

        # 2. 始终使用 staging 目录，所有写入先发往 staging，提交时再原子重命名
        self.new_workspace.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(
            prefix=f".{self.new_workspace.name}.migrating.",
            dir=str(self.new_workspace.parent),
        ))
        self._target = staging
        logger.debug("Using staging directory: %s", staging)

        try:
            stats = self._run_migration(run_data)
        except Exception:
            # 事务回滚：清理 staging 中间态
            shutil.rmtree(staging, ignore_errors=True)
            logger.warning("Migration aborted, staging dir removed: %s", staging)
            raise

        # 3. 提交：staging 原子重命名为最终目录
        try:
            # 若目标已存在（半成品续传），先整体删除以便 os.replace 接管
            if self.new_workspace.exists():
                shutil.rmtree(self.new_workspace)
            os.replace(str(staging), str(self.new_workspace))
            self._target = self.new_workspace
            logger.debug("Committed staging -> %s", self.new_workspace)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            logger.error("Failed to commit staging dir: %s", exc)
            raise

        logger.info(
            "Migration complete: %d succeeded, %d failed",
            len(stats["migrated_samples"]),
            len(stats["failed_samples"]),
        )
        return stats

    def _run_migration(self, run_data: dict) -> dict[str, Any]:
        """在 ``self._target`` 指向的目录上执行实际迁移动作。"""
        stats = {
            "migrated_samples": [],
            "failed_samples": [],
            "total_samples": 0,
        }
        self._target.mkdir(parents=True, exist_ok=True)

        prompt_results = run_data.get("prompt_results", [])
        for prompt_result in prompt_results:
            sample_id = prompt_result.get("sample_id") or prompt_result.get("prompt_id")
            platform = prompt_result.get("platform", "unknown")

            if not sample_id:
                continue

            stats["total_samples"] += 1

            try:
                self._migrate_sample(sample_id, platform, prompt_result)
                stats["migrated_samples"].append(sample_id)
                logger.info("✓ Migrated: %s/%s", sample_id, platform)
            except Exception as e:
                stats["failed_samples"].append({
                    "sample_id": sample_id,
                    "platform": platform,
                    "error": str(e),
                })
                logger.error("✗ Failed to migrate %s/%s: %s", sample_id, platform, e)

        self._copy_workspace_files()
        return stats

    def _migrate_sample(
        self,
        sample_id: str,
        platform: str,
        prompt_result: dict,
    ) -> None:
        """Migrate a single sample (writes into ``self._target``)."""
        sample_dir = self._target / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)

        # 1. Migrate generated projects
        old_project_dir = self.old_workspace / "generated_projects" / sample_id / platform
        new_project_dir = sample_dir / "generated_projects" / platform

        if old_project_dir.exists():
            shutil.copytree(old_project_dir, new_project_dir)
            logger.debug("  Copied: generated_projects/%s/%s", sample_id, platform)

        # 2. Migrate E2E reports (discover generator subdir dynamically)
        old_e2e_base = self.old_workspace / "e2e_reports"
        old_e2e_dir = None
        if old_e2e_base.exists():
            for gen_dir in old_e2e_base.iterdir():
                if gen_dir.is_dir() and (gen_dir / sample_id).exists():
                    old_e2e_dir = gen_dir / sample_id
                    break
        new_e2e_dir = sample_dir / "e2e_reports" / platform

        if old_e2e_dir and old_e2e_dir.exists():
            shutil.copytree(old_e2e_dir, new_e2e_dir)
            logger.debug("  Copied: e2e_reports/%s", sample_id)

        # 3. Generate sample report from prompt_result（原子写入）
        atomic_write_json(sample_dir / "sample_report.json", prompt_result)
        logger.debug("  Created: sample_report.json")

    def _copy_workspace_files(self) -> None:
        """Copy workspace-level files into ``self._target``."""
        for log_file in self.old_workspace.glob("exe_log_*.txt"):
            dest = self._target / log_file.name
            if not dest.exists():
                shutil.copy2(log_file, dest)
                logger.debug("Copied: %s", log_file.name)

        for report_file in ["report.html", "report_data.json"]:
            src = self.old_workspace / report_file
            if src.exists():
                dest = self._target / f"old_{report_file}"
                if not dest.exists():
                    shutil.copy2(src, dest)
                    logger.debug("Copied: %s -> old_%s", report_file, report_file)


def migrate_workspace(old_workspace: Path, new_workspace: Path) -> dict[str, Any]:
    """Convenience function to migrate a workspace.

    Args:
        old_workspace: Path to old workspace
        new_workspace: Path to new workspace

    Returns:
        Migration statistics
    """
    migrator = WorkspaceMigrator(old_workspace, new_workspace)
    return migrator.migrate()
