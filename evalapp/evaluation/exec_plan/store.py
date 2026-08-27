"""Load and manage execution plans from YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ...benchset.samples.models import EvalSample
from ...benchset.samples.store import SampleStore


class ExecPlanStore:
    """Load and manage execution plans."""

    def __init__(self, exec_plan_file: Path, project_root: Path) -> None:
        self.exec_plan_file = exec_plan_file
        self.project_root = project_root
        self._plan_data: dict[str, Any] = {}
        self._sample_stores: dict[str, SampleStore] = {}  # dataset_path -> SampleStore
        self._load()

    def _load(self) -> None:
        """Load execution plan and associated datasets."""
        if not self.exec_plan_file.exists():
            raise FileNotFoundError(f"Execution plan file not found: {self.exec_plan_file}")

        # Load execution plan YAML
        with open(self.exec_plan_file) as f:
            self._plan_data = yaml.safe_load(f) or {}

        # Load all datasets referenced in the plan
        datasets = self._plan_data.get("datasets", [])
        for dataset_path in datasets:
            # Resolve path relative to project root
            full_path = self.project_root / dataset_path
            if not full_path.exists():
                # Search in version subdirectories (V1, V2, etc.)
                dataset_root = self.project_root / "dataset"
                category_name = Path(dataset_path).name
                found = False
                if dataset_root.is_dir():
                    for version_dir in sorted(dataset_root.iterdir()):
                        if not version_dir.is_dir():
                            continue
                        candidate = version_dir / category_name
                        if candidate.is_dir():
                            full_path = candidate
                            found = True
                            break
                if not found:
                    raise FileNotFoundError(f"Dataset directory not found: {full_path}")
            
            # Create SampleStore for this dataset
            sample_store = SampleStore(full_path)
            self._sample_stores[dataset_path] = sample_store

        # Validate that all tasks reference valid samples
        self._validate_tasks()

    def _validate_tasks(self) -> None:
        """Validate that all tasks reference samples that exist in loaded datasets."""
        tasks = self._plan_data.get("tasks", [])
        for task in tasks:
            sample_id = task.get("sample_id")
            if not sample_id:
                raise ValueError(f"Task missing sample_id: {task}")
            
            # Check if sample exists in any loaded dataset
            if self.get_sample(sample_id) is None:
                raise ValueError(
                    f"Sample '{sample_id}' referenced in task not found in any loaded dataset. "
                    f"Available samples: {list(self._get_all_sample_ids())}"
                )

    def _get_all_sample_ids(self) -> set[str]:
        """Get all sample IDs from all loaded datasets."""
        sample_ids = set()
        for store in self._sample_stores.values():
            sample_ids.update(store._samples.keys())
        return sample_ids

    def get_tasks(self) -> list[dict[str, Any]]:
        """Return execution tasks from plan."""
        return self._plan_data.get("tasks", [])

    def get_sample(self, sample_id: str) -> EvalSample | None:
        """Find sample across all loaded dataset stores."""
        for store in self._sample_stores.values():
            sample = store.get(sample_id)
            if sample:
                return sample
        return None

    @property
    def plan_name(self) -> str:
        """Return the name of the execution plan."""
        return self._plan_data.get("name", "Unnamed Plan")

    @property
    def plan_description(self) -> str:
        """Return the description of the execution plan."""
        return self._plan_data.get("description", "")

    def list_datasets(self) -> list[str]:
        """Return list of dataset paths referenced in this plan."""
        return self._plan_data.get("datasets", [])

    def list_resolved_dataset_dirs(self) -> list[Path]:
        """Return resolved (existing) dataset directory paths.

        Unlike list_datasets() which returns raw strings from the YAML,
        this returns the actual filesystem paths after version-subdirectory
        resolution (e.g. dataset/V2/beverage instead of dataset/beverage).
        """
        return [store.samples_dir for store in self._sample_stores.values()]
