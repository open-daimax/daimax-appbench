"""Code quality metrics: static scan, cyclomatic complexity, and duplication.

Runs platform-appropriate static analysis tools against generated project
source code and aggregates the results into CodeQualityMetrics.

Supported tools:
- Android: Android Lint (``./gradlew lint``), optional detekt
- iOS: SwiftLint (``swiftlint lint``)
- Mini-program: ESLint (``npx eslint``)
- Cross-platform: lizard (cyclomatic complexity), jscpd (duplication)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..models import (
    CodeQualityMetrics,
    ComplexityResult,
    DuplicationResult,
    LintIssue,
    StaticScanResult,
)

logger = logging.getLogger(__name__)

# Default timeout for tool invocations (seconds)
_DEFAULT_TOOL_TIMEOUT = 300

# Cyclomatic complexity threshold – functions above this are flagged
_DEFAULT_CC_THRESHOLD = 15


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_code_quality_metrics(
    project_path: str,
    platform: str,
    *,
    tool_timeout: int = _DEFAULT_TOOL_TIMEOUT,
    cc_threshold: int = _DEFAULT_CC_THRESHOLD,
    skip_complexity: bool = False,
    skip_duplication: bool = False,
) -> CodeQualityMetrics:
    """Run static analysis tools and return aggregated code quality metrics.

    Args:
        project_path: Path to the generated project root.
        platform: ``"android"``, ``"ios"``, or ``"miniprogram"``.
        tool_timeout: Maximum seconds for each tool invocation.
        cc_threshold: Cyclomatic complexity threshold for flagging functions.
        skip_complexity: If True, skip complexity analysis (e.g. lizard not installed).
        skip_duplication: If True, skip duplication detection (e.g. jscpd not installed).

    Returns:
        CodeQualityMetrics with all collected sub-results.
    """
    scan_results: list[StaticScanResult] = []

    # --- Static scan (platform-specific) ---
    if platform == "android":
        scan_results.append(
            run_android_lint(project_path, timeout=tool_timeout)
        )
    elif platform == "ios":
        scan_results.append(
            run_swiftlint(project_path, timeout=tool_timeout)
        )
    elif platform == "miniprogram":
        scan_results.append(
            run_eslint(project_path, timeout=tool_timeout)
        )
    else:
        logger.warning("Unsupported platform for static scan: %s", platform)

    # --- Cyclomatic complexity (cross-platform) ---
    complexity_result = ComplexityResult()
    if not skip_complexity:
        complexity_result = run_lizard(
            project_path, platform, threshold=cc_threshold, timeout=tool_timeout
        )

    # --- Duplicate code detection (cross-platform) ---
    duplication_result = DuplicationResult()
    if not skip_duplication:
        duplication_result = run_jscpd(
            project_path, platform, timeout=tool_timeout
        )

    return _aggregate_metrics(scan_results, complexity_result, duplication_result)


# ---------------------------------------------------------------------------
# Android Lint
# ---------------------------------------------------------------------------


def run_android_lint(
    project_path: str, *, timeout: int = _DEFAULT_TOOL_TIMEOUT
) -> StaticScanResult:
    """Run Android Lint via Gradle and parse the XML report."""
    project_root = Path(project_path)
    gradlew = project_root / "gradlew"
    if not gradlew.exists():
        return StaticScanResult(
            tool="android_lint",
            success=False,
            error_message="gradlew not found in project root",
        )

    # Ensure gradlew is executable
    try:
        gradlew.chmod(gradlew.stat().st_mode | 0o111)
    except OSError as e:
        logger.debug("chmod gradlew 失败 (path=%s): %s", gradlew, e)

    cmd = [str(gradlew), "lint", "--quiet"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_path,
            env=_clean_env(),
        )
    except FileNotFoundError:
        return StaticScanResult(
            tool="android_lint",
            success=False,
            error_message="Failed to execute gradlew (not found)",
        )
    except subprocess.TimeoutExpired:
        return StaticScanResult(
            tool="android_lint",
            success=False,
            error_message=f"Android Lint timed out after {timeout}s",
        )

    # Find lint report XML – Gradle places it in app/build/reports/lint-results*.xml
    report_path = _find_lint_report(project_root)
    if report_path is None:
        # Lint may have run but produced no report (no issues or broken config)
        return StaticScanResult(
            tool="android_lint",
            success=proc.returncode == 0,
            error_message="" if proc.returncode == 0 else (
                f"Lint exited with code {proc.returncode} and no report found"
            ),
        )

    return _parse_android_lint_xml(report_path)


def _find_lint_report(project_root: Path) -> Path | None:
    """Locate the Android Lint XML report in build output."""
    candidates = [
        project_root / "app" / "build" / "reports" / "lint-results-debug.xml",
        project_root / "app" / "build" / "reports" / "lint-results.xml",
    ]
    for path in candidates:
        if path.exists():
            return path
    # Fallback: search for any lint-results*.xml
    for path in project_root.rglob("lint-results*.xml"):
        if "build" in path.parts:
            return path
    return None


def _parse_android_lint_xml(report_path: Path) -> StaticScanResult:
    """Parse Android Lint XML report into a StaticScanResult."""
    issues: list[LintIssue] = []
    error_count = 0
    warning_count = 0
    info_count = 0

    try:
        tree = ET.parse(report_path)
        root = tree.getroot()

        for issue_elem in root.iter("issue"):
            severity = (issue_elem.get("severity") or "").lower()
            location = issue_elem.find("location")
            file_path = ""
            line_num = 0
            column_num = 0
            if location is not None:
                file_path = location.get("file", "")
                line_num = int(location.get("line", "0") or "0")
                column_num = int(location.get("column", "0") or "0")

            lint_issue = LintIssue(
                rule_id=issue_elem.get("id", ""),
                severity=severity,
                message=issue_elem.get("message", ""),
                file=file_path,
                line=line_num,
                column=column_num,
                source="android_lint",
            )
            issues.append(lint_issue)

            if severity in ("error", "fatal"):
                error_count += 1
            elif severity == "warning":
                warning_count += 1
            else:
                info_count += 1

    except ET.ParseError as exc:
        return StaticScanResult(
            tool="android_lint",
            success=False,
            error_message=f"Failed to parse lint report: {exc}",
            raw_output_path=str(report_path),
        )

    return StaticScanResult(
        tool="android_lint",
        success=True,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        total_issues=len(issues),
        issues=issues,
        raw_output_path=str(report_path),
    )


# ---------------------------------------------------------------------------
# SwiftLint
# ---------------------------------------------------------------------------


def run_swiftlint(
    project_path: str, *, timeout: int = _DEFAULT_TOOL_TIMEOUT
) -> StaticScanResult:
    """Run SwiftLint and parse JSON output."""
    cmd = ["swiftlint", "lint", "--reporter", "json", "--quiet", "--path", project_path]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_path,
            env=_clean_env(),
        )
    except FileNotFoundError:
        return StaticScanResult(
            tool="swiftlint",
            success=False,
            error_message="swiftlint not found – install via `brew install swiftlint`",
        )
    except subprocess.TimeoutExpired:
        return StaticScanResult(
            tool="swiftlint",
            success=False,
            error_message=f"SwiftLint timed out after {timeout}s",
        )

    return _parse_swiftlint_json(proc.stdout or "")


def _parse_swiftlint_json(json_text: str) -> StaticScanResult:
    """Parse SwiftLint JSON reporter output."""
    issues: list[LintIssue] = []
    error_count = 0
    warning_count = 0
    info_count = 0

    try:
        entries: list[dict[str, Any]] = json.loads(json_text) if json_text.strip() else []
    except json.JSONDecodeError as exc:
        return StaticScanResult(
            tool="swiftlint",
            success=False,
            error_message=f"Failed to parse SwiftLint JSON: {exc}",
        )

    for entry in entries:
        severity = (entry.get("severity") or "").lower()
        # SwiftLint uses "Warning", "Error"
        if severity == "warning":
            warning_count += 1
        elif severity == "error":
            error_count += 1
        else:
            info_count += 1

        issues.append(LintIssue(
            rule_id=entry.get("rule_id", ""),
            severity=severity,
            message=entry.get("reason", ""),
            file=entry.get("file", ""),
            line=entry.get("line", 0),
            column=entry.get("character", 0),
            source="swiftlint",
        ))

    return StaticScanResult(
        tool="swiftlint",
        success=True,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        total_issues=len(issues),
        issues=issues,
    )


# ---------------------------------------------------------------------------
# ESLint (mini-program)
# ---------------------------------------------------------------------------


def run_eslint(
    project_path: str, *, timeout: int = _DEFAULT_TOOL_TIMEOUT
) -> StaticScanResult:
    """Run ESLint for mini-program projects and parse JSON output.

    Attempts to use the project-local ESLint first (``npx eslint``), falling
    back to a globally installed ``eslint`` binary.  The ``--format json``
    reporter is used so that output can be parsed programmatically.
    """
    project_root = Path(project_path)

    # Determine source directories – mini-program projects commonly have
    # ``pages/``, ``components/``, ``utils/``, or ``src/`` directories.
    src_dirs: list[str] = []
    for candidate in ("pages", "components", "utils", "src", "miniprogram"):
        if (project_root / candidate).is_dir():
            src_dirs.append(candidate)
    if not src_dirs:
        # Fallback: lint the entire project root
        src_dirs = ["."]

    # Build command – prefer npx so we pick up a locally-installed eslint and
    # any project-specific config (.eslintrc.*) automatically.
    cmd = [
        "npx", "--yes", "eslint",
        "--format", "json",
        "--no-error-on-unmatched-pattern",
        "--ext", ".js,.ts,.wxs,.wxml,.vue,.json",
    ]
    cmd.extend(src_dirs)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_path,
            env=_clean_env(),
        )
    except FileNotFoundError:
        return StaticScanResult(
            tool="eslint",
            success=False,
            error_message="eslint / npx not found – install via `npm install -g eslint`",
        )
    except subprocess.TimeoutExpired:
        return StaticScanResult(
            tool="eslint",
            success=False,
            error_message=f"ESLint timed out after {timeout}s",
        )

    return _parse_eslint_json(proc.stdout or "")


def _parse_eslint_json(json_text: str) -> StaticScanResult:
    """Parse ESLint ``--format json`` output.

    ESLint JSON reporter emits an array of file-level result objects::

        [
          {
            "filePath": "/project/pages/index/index.js",
            "messages": [
              {
                "ruleId": "no-unused-vars",
                "severity": 2,
                "message": "'x' is defined but never used.",
                "line": 5,
                "column": 7
              }
            ],
            "errorCount": 0,
            "warningCount": 1
          }
        ]

    ``severity`` values: 1 = warning, 2 = error.
    """
    issues: list[LintIssue] = []
    error_count = 0
    warning_count = 0
    info_count = 0

    if not json_text.strip():
        # No output usually means no files matched or eslint was not configured
        return StaticScanResult(
            tool="eslint",
            success=True,
            error_message="",
        )

    try:
        file_results: list[dict[str, Any]] = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return StaticScanResult(
            tool="eslint",
            success=False,
            error_message=f"Failed to parse ESLint JSON: {exc}",
        )

    for file_result in file_results:
        file_path = file_result.get("filePath", "")
        for msg in file_result.get("messages", []):
            severity_num = msg.get("severity", 0)
            if severity_num == 2:
                severity = "error"
                error_count += 1
            elif severity_num == 1:
                severity = "warning"
                warning_count += 1
            else:
                severity = "info"
                info_count += 1

            issues.append(LintIssue(
                rule_id=msg.get("ruleId", "") or "",
                severity=severity,
                message=msg.get("message", ""),
                file=file_path,
                line=msg.get("line", 0),
                column=msg.get("column", 0),
                source="eslint",
            ))

    return StaticScanResult(
        tool="eslint",
        success=True,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        total_issues=len(issues),
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Cyclomatic complexity (lizard)
# ---------------------------------------------------------------------------

# Language extensions for lizard analysis by platform
_LANG_EXTENSIONS: dict[str, list[str]] = {
    "android": [".kt", ".java"],
    "ios": [".swift"],
    "miniprogram": [".js", ".ts"],
}


def run_lizard(
    project_path: str,
    platform: str,
    *,
    threshold: int = _DEFAULT_CC_THRESHOLD,
    timeout: int = _DEFAULT_TOOL_TIMEOUT,
) -> ComplexityResult:
    """Run lizard cyclomatic complexity analysis."""
    extensions = _LANG_EXTENSIONS.get(platform, [])
    if not extensions:
        return ComplexityResult(
            success=False,
            error_message=f"No language extensions configured for platform: {platform}",
        )

    cmd = [
        "lizard",
        project_path,
        "--xml",
        f"--CCN={threshold}",
    ]
    for ext in extensions:
        cmd.extend(["-l", ext.lstrip(".")])

    # Exclude build / dependency directories
    cmd.extend([
        "-x", "*/build/*",
        "-x", "*/Pods/*",
        "-x", "*/node_modules/*",
        "-x", "*/.gradle/*",
        "-x", "*/DerivedData/*",
    ])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_env(),
        )
    except FileNotFoundError:
        return ComplexityResult(
            success=False,
            error_message="lizard not found – install via `pip install lizard`",
        )
    except subprocess.TimeoutExpired:
        return ComplexityResult(
            success=False,
            error_message=f"lizard timed out after {timeout}s",
        )

    return _parse_lizard_xml(proc.stdout or "", threshold)


def _parse_lizard_xml(xml_text: str, threshold: int) -> ComplexityResult:
    """Parse lizard XML output."""
    if not xml_text.strip():
        return ComplexityResult(
            success=False,
            error_message="lizard produced no output",
        )

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return ComplexityResult(
            success=False,
            error_message=f"Failed to parse lizard XML: {exc}",
        )

    total_functions = 0
    total_complexity = 0.0
    max_complexity = 0.0
    over_threshold = 0
    high_funcs: list[dict[str, object]] = []

    # lizard XML structure: <cppncss> -> <measure type="Function"> -> <item>
    for measure in root.iter("measure"):
        if measure.get("type") != "Function":
            continue
        for item in measure.iter("item"):
            total_functions += 1
            # Values are in <value> sub-elements
            values = [v.text for v in item.findall("value")]
            # lizard XML: NCSS, CCN, token, PARAM, length
            if len(values) >= 2:
                try:
                    cc = float(values[1])
                except (ValueError, TypeError):
                    cc = 0.0
            else:
                cc = 0.0

            total_complexity += cc
            if cc > max_complexity:
                max_complexity = cc

            if cc > threshold:
                over_threshold += 1
                func_name = item.get("name", "")
                high_funcs.append({
                    "name": func_name,
                    "complexity": cc,
                    "file": _extract_file_from_lizard_name(func_name),
                    "line": 0,
                })

    avg = total_complexity / total_functions if total_functions > 0 else 0.0

    return ComplexityResult(
        tool="lizard",
        success=True,
        total_functions=total_functions,
        avg_complexity=round(avg, 2),
        max_complexity=max_complexity,
        functions_over_threshold=over_threshold,
        complexity_threshold=threshold,
        high_complexity_functions=high_funcs,
    )


def _extract_file_from_lizard_name(name: str) -> str:
    """Extract file path from lizard's function name (e.g. 'file.kt::Class::method')."""
    if "::" in name:
        return name.split("::")[0]
    return ""


# ---------------------------------------------------------------------------
# Duplicate code detection (jscpd)
# ---------------------------------------------------------------------------

_JSCPD_FORMAT_MAP: dict[str, str] = {
    "android": "kotlin,java",
    "ios": "swift,objectivec",
    "miniprogram": "javascript,typescript",
}


def run_jscpd(
    project_path: str,
    platform: str,
    *,
    timeout: int = _DEFAULT_TOOL_TIMEOUT,
) -> DuplicationResult:
    """Run jscpd duplicate code detection."""
    formats = _JSCPD_FORMAT_MAP.get(platform, "")
    if not formats:
        return DuplicationResult(
            success=False,
            error_message=f"No language formats configured for platform: {platform}",
        )

    cmd = [
        "jscpd",
        project_path,
        "--reporters", "json",
        "--format", formats,
        "--silent",
        "--ignore", "build,Pods,node_modules,.gradle,DerivedData",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_path,
            env=_clean_env(),
        )
    except FileNotFoundError:
        return DuplicationResult(
            success=False,
            error_message="jscpd not found – install via `npm install -g jscpd`",
        )
    except subprocess.TimeoutExpired:
        return DuplicationResult(
            success=False,
            error_message=f"jscpd timed out after {timeout}s",
        )

    return _parse_jscpd_output(proc.stdout or "", project_path)


def _parse_jscpd_output(
    stdout: str, project_path: str
) -> DuplicationResult:
    """Parse jscpd JSON reporter output or fall back to report file."""
    # jscpd may write to report/ directory instead of stdout
    report_file = Path(project_path) / "report" / "jscpd-report.json"

    json_text = stdout.strip()
    if not json_text and report_file.exists():
        try:
            json_text = report_file.read_text()
        except OSError as e:
            logger.debug("读取 jscpd 报告文件失败 (path=%s): %s", report_file, e)

    if not json_text:
        return DuplicationResult(
            success=False,
            error_message="jscpd produced no output",
        )

    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return DuplicationResult(
            success=False,
            error_message=f"Failed to parse jscpd JSON: {exc}",
        )

    statistics = data.get("statistics", {})
    total = statistics.get("total", {})
    total_lines = int(total.get("lines", 0))
    duplicated_lines = int(total.get("duplicatedLines", 0))
    dup_rate = duplicated_lines / total_lines if total_lines > 0 else 0.0

    clones_raw = data.get("duplicates", [])
    clones: list[dict[str, object]] = []
    for clone in clones_raw[:50]:  # Cap at 50 for storage
        clones.append({
            "source_file": clone.get("firstFile", {}).get("name", ""),
            "target_file": clone.get("secondFile", {}).get("name", ""),
            "lines": clone.get("lines", 0),
        })

    return DuplicationResult(
        tool="jscpd",
        success=True,
        total_lines=total_lines,
        duplicated_lines=duplicated_lines,
        duplication_rate=round(dup_rate, 4),
        clone_count=len(clones_raw),
        clones=clones,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate_metrics(
    scan_results: list[StaticScanResult],
    complexity_result: ComplexityResult,
    duplication_result: DuplicationResult,
) -> CodeQualityMetrics:
    """Aggregate sub-tool results into a single CodeQualityMetrics."""
    total_issues = 0
    error_count = 0
    warning_count = 0
    info_count = 0

    for sr in scan_results:
        if sr.success:
            total_issues += sr.total_issues
            error_count += sr.error_count
            warning_count += sr.warning_count
            info_count += sr.info_count

    # Convention compliance rate: files without errors or warnings
    # Approximation: 1.0 - (error+warning) / max(total_issues, 1)
    significant_issues = error_count + warning_count
    compliance_rate = (
        1.0 - significant_issues / max(total_issues, 1)
        if total_issues > 0
        else 1.0 if any(sr.success for sr in scan_results) else 0.0
    )

    high_complexity_ratio = 0.0
    if complexity_result.success and complexity_result.total_functions > 0:
        high_complexity_ratio = (
            complexity_result.functions_over_threshold
            / complexity_result.total_functions
        )

    return CodeQualityMetrics(
        total_issues=total_issues,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        convention_compliance_rate=round(compliance_rate, 4),
        avg_complexity=complexity_result.avg_complexity if complexity_result.success else 0.0,
        max_complexity=complexity_result.max_complexity if complexity_result.success else 0.0,
        high_complexity_ratio=round(high_complexity_ratio, 4),
        duplication_rate=duplication_result.duplication_rate if duplication_result.success else 0.0,
        scan_results=scan_results,
        complexity_result=complexity_result,
        duplication_result=duplication_result,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_env() -> dict[str, str]:
    """Return a clean subprocess environment (strip CLAUDECODE to avoid interference)."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
