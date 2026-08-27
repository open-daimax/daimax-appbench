"""TestCaseStore: persists and retrieves structured test cases."""

from __future__ import annotations

import json
from pathlib import Path

from ...utils.logging import get_logger
from ...utils.paths import get_project_root
from .models import TestCase, TestDesignOutput

logger = get_logger(__name__)

# Expo 平台复用已有平台的测试用例：当目标平台文件不存在时，回退到映射的平台文件
PLATFORM_TESTCASE_FALLBACK: dict[str, str] = {
    "expo_android": "android",
    "expo_ios": "ios",
    "expo_web": "h5",
}


class TestCaseStore:
    """Manages test case storage on disk.

    Storage layout:
        test_cases/{prompt_id}/{platform}/test_cases.json

    Supports multiple search directories: when test_cases_dir is a list of
    directories, load() / exists() / list_all() will search all of them
    in order, returning the first match.  This enables multi-dataset
    evaluation where samples are scattered across category sub-directories
    (games/, map/, social/, tools/).
    """

    def __init__(self, test_cases_dir: Path | list[Path]) -> None:
        if isinstance(test_cases_dir, list):
            self._test_cases_dirs = test_cases_dir
        else:
            self._test_cases_dirs = [test_cases_dir]

    @property
    def test_cases_dir(self) -> Path:
        """Primary test cases directory (first in search list).

        Kept for backward compatibility with code that expects a single Path.
        """
        return self._test_cases_dirs[0]

    def save(self, design_output: TestDesignOutput) -> Path:
        """Save test design output to disk.

        Returns the path to the saved test_cases.json file.
        """
        tc_dir = self.test_cases_dir / design_output.prompt_id / design_output.platform
        tc_dir.mkdir(parents=True, exist_ok=True)

        # Save structured test cases
        tc_file = tc_dir / "test_cases.json"
        data = {
            "prompt_id": design_output.prompt_id,
            "platform": design_output.platform,
            "test_cases": [tc.model_dump() for tc in design_output.test_cases],
        }
        with open(tc_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        if design_output.raw_output:
            raw_file = tc_dir / "raw_output.txt"
            with open(raw_file, "w") as f:
                f.write(design_output.raw_output)

        logger.info(f"Saved {len(design_output.test_cases)} test cases to {tc_file}")
        return tc_file

    def load(self, prompt_id: str, platform: str) -> list[TestCase]:
        """Load test cases for a given prompt and platform.
        
        Searches all configured directories in order.  Supports two formats:
        1. New format: {test_cases_dir}/{prompt_id}/test_cases/test_cases_{platform}.json
        2. Old format: {test_cases_dir}/{prompt_id}/{platform}/test_cases.json
        
        When the target platform file does not exist, falls back to the
        mapped platform defined in PLATFORM_TESTCASE_FALLBACK (e.g. expo_android → android).
        """
        # 先尝试原始 platform
        for base_dir in self._test_cases_dirs:
            # Try new format first
            new_format_file = base_dir / prompt_id / "test_cases" / f"test_cases_{platform}.json"
            if new_format_file.exists():
                with open(new_format_file) as f:
                    data = json.load(f)
                logger.info(f"Loaded {len(data.get('test_cases', []))} test cases from {new_format_file}")
                return self._inject_tc_launch([TestCase(**tc) for tc in data.get("test_cases", [])])
            
            # Try old format
            tc_file = base_dir / prompt_id / platform / "test_cases.json"
            if tc_file.exists():
                with open(tc_file) as f:
                    data = json.load(f)
                logger.info(f"Loaded {len(data.get('test_cases', []))} test cases from {tc_file}")
                return self._inject_tc_launch([TestCase(**tc) for tc in data.get("test_cases", [])])

        # 原始 platform 未找到，尝试 fallback
        fallback_platform = PLATFORM_TESTCASE_FALLBACK.get(platform)
        if fallback_platform:
            logger.info(
                f"Test cases for {platform} not found, "
                f"falling back to {fallback_platform}"
            )
            for base_dir in self._test_cases_dirs:
                # Try new format
                new_format_file = base_dir / prompt_id / "test_cases" / f"test_cases_{fallback_platform}.json"
                if new_format_file.exists():
                    with open(new_format_file) as f:
                        data = json.load(f)
                    logger.info(f"Loaded {len(data.get('test_cases', []))} test cases from {new_format_file} (fallback from {platform})")
                    return self._inject_tc_launch([TestCase(**tc) for tc in data.get("test_cases", [])])
                
                # Try old format
                tc_file = base_dir / prompt_id / fallback_platform / "test_cases.json"
                if tc_file.exists():
                    with open(tc_file) as f:
                        data = json.load(f)
                    logger.info(f"Loaded {len(data.get('test_cases', []))} test cases from {tc_file} (fallback from {platform})")
                    return self._inject_tc_launch([TestCase(**tc) for tc in data.get("test_cases", [])])

        # 所有平台映射均未命中，回退到 default 测试用例
        if platform != "default":
            logger.info(
                f"Test cases for {platform} not found, "
                f"falling back to default"
            )
            for base_dir in self._test_cases_dirs:
                # Try new format
                new_format_file = base_dir / prompt_id / "test_cases" / "test_cases_default.json"
                if new_format_file.exists():
                    with open(new_format_file) as f:
                        data = json.load(f)
                    logger.info(f"Loaded {len(data.get('test_cases', []))} test cases from {new_format_file} (fallback from {platform})")
                    return self._inject_tc_launch([TestCase(**tc) for tc in data.get("test_cases", [])])

                # Try old format
                tc_file = base_dir / prompt_id / "default" / "test_cases.json"
                if tc_file.exists():
                    with open(tc_file) as f:
                        data = json.load(f)
                    logger.info(f"Loaded {len(data.get('test_cases', []))} test cases from {tc_file} (fallback from {platform})")
                    return self._inject_tc_launch([TestCase(**tc) for tc in data.get("test_cases", [])])

        logger.warning(
            f"No test cases found for {prompt_id}/{platform} "
            f"in directories: {self._test_cases_dirs}"
        )
        return self._inject_tc_launch([])

    def _inject_tc_launch(self, test_cases: list[TestCase]) -> list[TestCase]:
        """Inject TC_LAUNCH from the shared common template if not present.

        The template is resolved relative to the currently configured
        sample directories (see ``_resolve_tc_launch_template``).  When
        the template cannot be located, a warning is logged with every
        candidate path tried so the operator can pinpoint the
        misconfiguration instead of silently losing the launch gate
        (a missing TC_LAUNCH previously left samples ungated).
        """
        # Skip if TC_LAUNCH already exists
        if any(tc.id == "TC_LAUNCH" for tc in test_cases):
            return test_cases

        template_path, tried_paths = self._resolve_tc_launch_template()
        if template_path is None:
            logger.warning(
                "TC_LAUNCH template not found; launch gating disabled. "
                "Tried paths: %s",
                "; ".join(str(p) for p in tried_paths) or "(none)",
            )
            return test_cases

        try:
            with open(template_path) as f:
                tpl_data = json.load(f)
            tc_launch_data = tpl_data.get("tc_launch")
            if not tc_launch_data:
                logger.warning(
                    "TC_LAUNCH template at %s has no 'tc_launch' key",
                    template_path,
                )
                return test_cases

            # Ensure 'description' field exists (TestCase requires it)
            if "description" not in tc_launch_data:
                tc_launch_data["description"] = tc_launch_data.get(
                    "name", "应用启动验证"
                )

            # Remove fields not in TestCase model
            tc_launch_data.pop("notes", None)

            tc_launch = TestCase(**tc_launch_data)
            test_cases.insert(0, tc_launch)
            logger.info("Injected TC_LAUNCH from %s", template_path)
        except Exception as e:
            logger.warning(
                "Failed to inject TC_LAUNCH from %s: %s", template_path, e
            )

        return test_cases

    def _resolve_tc_launch_template(self) -> tuple[Path | None, list[Path]]:
        """Resolve the TC_LAUNCH template path for the active sample dirs.

        Strategy:
          1. Walk up from each configured test-cases directory looking for
             ``common/tc_launch_template.json``. This finds the template
             that belongs to the same dataset version as the active
             samples (e.g. ``dataset/V2/common/...`` when samples live
             under ``dataset/V2/<category>/``).
          2. Fall back to the canonical project-root layout, trying the
             newest version first (V2 → V1).

        Returns ``(template_path_or_None, tried_paths)``. ``tried_paths``
        is de-duplicated and ordered so callers can emit a precise log
        message when the template cannot be located.
        """
        tried: list[Path] = []
        seen: set[str] = set()

        def _consider(candidate: Path) -> bool:
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                tried.append(candidate)
            return candidate.is_file()

        # 1. Walk up from each configured sample directory.
        for base_dir in self._test_cases_dirs:
            current = Path(base_dir)
            ancestors = [current, *current.parents]
            for ancestor in ancestors:
                if _consider(ancestor / "common" / "tc_launch_template.json"):
                    return ancestor / "common" / "tc_launch_template.json", tried
                # The ``dataset`` root has no version-level ``common/``;
                # stop here to avoid surfacing unrelated matches above.
                if ancestor.name == "dataset":
                    break

        # 2. Fall back to the canonical project-root dataset layout.
        project_root = get_project_root()
        for version in ("V2", "V1"):
            candidate = (
                project_root / "dataset" / version / "common"
                / "tc_launch_template.json"
            )
            if _consider(candidate):
                return candidate, tried

        return None, tried

    def exists(self, prompt_id: str, platform: str) -> bool:
        """Check if test cases exist for a given prompt and platform.
        
        Also checks fallback platforms defined in PLATFORM_TESTCASE_FALLBACK.
        """
        for base_dir in self._test_cases_dirs:
            # Check new format
            new_format_file = base_dir / prompt_id / "test_cases" / f"test_cases_{platform}.json"
            if new_format_file.exists():
                return True
            # Check old format
            tc_file = base_dir / prompt_id / platform / "test_cases.json"
            if tc_file.exists():
                return True

        # 尝试 fallback
        fallback_platform = PLATFORM_TESTCASE_FALLBACK.get(platform)
        if fallback_platform:
            for base_dir in self._test_cases_dirs:
                new_format_file = base_dir / prompt_id / "test_cases" / f"test_cases_{fallback_platform}.json"
                if new_format_file.exists():
                    return True
                tc_file = base_dir / prompt_id / fallback_platform / "test_cases.json"
                if tc_file.exists():
                    return True

        return False

    def list_all(self) -> list[dict]:
        """List all stored test case sets with metadata across all directories."""
        results: list[dict] = []
        seen: set[str] = set()  # track (prompt_id, platform) to avoid duplicates

        for base_dir in self._test_cases_dirs:
            if not base_dir.exists():
                continue

            # Scan new format: {base_dir}/{prompt_id}/test_cases/test_cases_{platform}.json
            for prompt_dir in sorted(base_dir.iterdir()):
                if not prompt_dir.is_dir():
                    continue
                tc_dir = prompt_dir / "test_cases"
                if tc_dir.exists():
                    for tc_file in sorted(tc_dir.glob("test_cases_*.json")):
                        # Extract platform from filename: test_cases_{platform}.json
                        platform = tc_file.stem[len("test_cases_"):]
                        key = f"{prompt_dir.name}/{platform}"
                        if key in seen:
                            continue
                        seen.add(key)
                        with open(tc_file) as f:
                            data = json.load(f)
                        results.append({
                            "prompt_id": prompt_dir.name,
                            "platform": platform,
                            "count": len(data.get("test_cases", [])),
                        })

            # Scan old format: {base_dir}/{prompt_id}/{platform}/test_cases.json
            for prompt_dir in sorted(base_dir.iterdir()):
                if not prompt_dir.is_dir():
                    continue
                for platform_dir in sorted(prompt_dir.iterdir()):
                    if not platform_dir.is_dir():
                        continue
                    tc_file = platform_dir / "test_cases.json"
                    key = f"{prompt_dir.name}/{platform_dir.name}"
                    if key in seen:
                        continue
                    if tc_file.exists():
                        seen.add(key)
                        with open(tc_file) as f:
                            data = json.load(f)
                        results.append({
                            "prompt_id": prompt_dir.name,
                            "platform": platform_dir.name,
                            "count": len(data.get("test_cases", [])),
                        })
        return results
