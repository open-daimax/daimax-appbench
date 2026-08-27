"""Load benchmark evaluation samples from a dataset directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import EvalSample


class SampleStore:
    """Loads EvalSample definitions from a dataset directory with execution plan support."""

    def __init__(self, samples_dir: Path) -> None:
        self.samples_dir = samples_dir
        self._samples: dict[str, EvalSample] = {}
        self._execution_plan: list[dict[str, Any]] = []
        self._load()

    @property
    def execution_plan(self) -> list[dict[str, Any]]:
        """Return the execution plan from index.yaml."""
        return self._execution_plan

    @property
    def test_cases_dir(self) -> Path:
        """Directory where generated sample test cases are stored.
        
        For new structure, returns the samples_dir root.
        TestCaseStore will append {sample_id}/test_cases/.
        For backward compatibility with old structure.
        """
        return self.samples_dir

    def _load(self) -> None:
        if not self.samples_dir.exists():
            return

        # Load index.yaml first
        index_file = self.samples_dir / "index.yaml"
        if index_file.exists():
            with open(index_file) as f:
                index_data = yaml.safe_load(f) or {}
            
            # Check if new format (has samples_index)
            if "samples_index" in index_data:
                # New format: load from directories
                self._execution_plan = index_data.get("execution_plan", [])
                
                for entry in index_data.get("samples_index", []):
                    if isinstance(entry, str):
                        dir_name = entry
                    else:
                        dir_name = entry.get("dir") if isinstance(entry, dict) else None
                    if not dir_name:
                        continue
                    sample_dir = self.samples_dir / dir_name
                    sample_file = sample_dir / "sample.yaml"
                    if sample_file.exists():
                        with open(sample_file) as f:
                            sample_data = yaml.safe_load(f) or {}
                        sample = EvalSample(**sample_data)
                        self._samples[sample.sample_id] = sample
            else:
                # Old format: load from files
                for entry in index_data.get("files", []):
                    if isinstance(entry, str):
                        file_name = entry
                    else:
                        file_name = entry.get("file") if isinstance(entry, dict) else None
                    if not file_name:
                        continue
                    yaml_file = self.samples_dir / file_name
                    if yaml_file.exists():
                        with open(yaml_file) as f:
                            data = yaml.safe_load(f) or {}
                        for item in data.get("samples", []):
                            sample = EvalSample(**item)
                            self._samples[sample.sample_id] = sample
        else:
            # Fallback to old format without index.yaml
            for yaml_file in self._old_sample_files():
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}

                for item in data.get("samples", []):
                    sample = EvalSample(**item)
                    self._samples[sample.sample_id] = sample

    def _old_sample_files(self) -> list[Path]:
        """Legacy method for old directory structure."""
        return sorted(self.samples_dir.glob("*_samples.yaml"))

    def list_all(self) -> list[EvalSample]:
        """Return all loaded samples."""
        return list(self._samples.values())

    def get(self, sample_id: str) -> EvalSample | None:
        """Get a sample by ID."""
        return self._samples.get(sample_id)

    def filter(
        self,
        sample_id: str | None = None,
        platform: str | None = None,
    ) -> list[EvalSample]:
        """Filter samples by criteria.
        
        Note: In new structure, platform filtering is handled by execution_plan.
        This method keeps platform filter for backward compatibility.
        """
        samples = self.list_all()
        if sample_id is not None:
            samples = [s for s in samples if s.sample_id == sample_id]
        if platform is not None:
            # Backward compatibility: filter by platforms field
            samples = [s for s in samples if platform in s.platforms]
        return samples

    def get_tasks(self, sample_id: str | None = None) -> list[dict[str, Any]]:
        """Get execution tasks from plan, optionally filtered by sample_id.
        
        Returns list of dicts with sample_id and platform.
        """
        if not self._execution_plan:
            # Fallback: generate tasks from samples
            tasks = []
            for sample in self.list_all():
                for platform in sample.platforms:
                    tasks.append({
                        "sample_id": sample.sample_id,
                        "platform": platform,
                    })
            return tasks
        
        # Filter execution plan
        tasks = self._execution_plan
        if sample_id:
            tasks = [t for t in tasks if t.get("sample_id") == sample_id]
        
        return tasks

    def filter_by_version(self, dataset_version: str = "v2") -> list[EvalSample]:
        """按 dataset_version 过滤样本"""
        return [s for s in self.list_all() if getattr(s, 'dataset_version', 'v1') == dataset_version]

    def get_active_samples(self, dataset_version: str | None = None) -> list[EvalSample]:
        """获取活跃样本，可选按版本过滤"""
        active = [s for s in self.list_all() if getattr(s, 'status', 'active') == 'active']
        if dataset_version:
            active = [s for s in active if getattr(s, 'dataset_version', 'v1') == dataset_version]
        return active

    def get_deprecated_samples(self) -> list[EvalSample]:
        """获取所有废弃样本"""
        return [s for s in self.list_all() if getattr(s, 'status', 'active') == 'deprecated']
