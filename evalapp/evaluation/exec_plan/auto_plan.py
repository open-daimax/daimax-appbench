"""Auto-generate sample-platform execution tasks from a dataset directory."""

from __future__ import annotations

from pathlib import Path

from ...benchset.samples.store import SampleStore


def auto_plan_from_dir(
    samples_dir: Path,
    platform: str,
    sample_ids: str | None = None,
) -> tuple[list[dict], list[Path]]:
    """Build sample-platform tasks by scanning a dataset directory.

    Args:
        samples_dir: A single category directory (e.g. ``dataset/V2/beverage``)
            or a version directory containing multiple categories
            (e.g. ``dataset/V2/``).
        platform: Internal platform identifier (e.g. ``"expo_web"``).
        sample_ids: Optional comma-separated sample IDs for filtering.

    Returns:
        A tuple ``(tasks, samples_dirs)`` where *tasks* is a list of
        task dicts ``{"sample", "platform", "end_case", "priority"}``
        and *samples_dirs* is the list of directories from which samples
        were successfully loaded.
    """
    stores: list[tuple[SampleStore, Path]] = []

    # Determine whether samples_dir is a single category directory or a
    # parent directory containing multiple category sub-directories.
    has_index = (samples_dir / "index.yaml").exists()
    has_sample = (samples_dir / "sample.yaml").exists()

    if has_index or has_sample:
        store = SampleStore(samples_dir)
        if store.list_all():
            stores.append((store, samples_dir))
    else:
        for child in sorted(samples_dir.iterdir()):
            if not child.is_dir():
                continue
            store = SampleStore(child)
            if store.list_all():
                stores.append((store, child))

    # Parse optional sample ID filter.
    id_filter: set[str] | None = None
    if sample_ids:
        ids = {sid.strip() for sid in sample_ids.split(",") if sid.strip()}
        if ids:
            id_filter = ids

    # Build task list from all loaded samples.
    tasks: list[dict] = []
    loaded_dirs: list[Path] = []

    for store, dir_path in stores:
        loaded_dirs.append(dir_path)
        for sample in store.list_all():
            if id_filter is not None and sample.sample_id not in id_filter:
                continue
            tasks.append({
                "sample": sample,
                "platform": platform,
                "end_case": None,
                "priority": None,
            })

    return tasks, loaded_dirs
