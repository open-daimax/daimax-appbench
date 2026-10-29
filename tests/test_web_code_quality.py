"""Web static analysis must distinguish findings, tool failure and no coverage."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import Mock

import pytest

from evalapp.evaluation.metrics.collectors import code_quality as collector
from evalapp.evaluation.metrics.dimensions.code_quality import _score_static_scan


@pytest.fixture
def web_project(tmp_path):
    (tmp_path / 'eslint.config.mjs').write_text('export default [];')
    executable = tmp_path / 'node_modules/.bin/eslint'
    executable.parent.mkdir(parents=True)
    executable.touch()
    return tmp_path


def report(messages=None):
    return json.dumps([{'filePath': '/project/src/app.jsx', 'messages': messages or []}])


def test_web_dispatch_and_clean_scan(web_project, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, report(), ''))
    monkeypatch.setattr(collector.subprocess, 'run', run)
    result = collector.collect_code_quality_metrics(
        str(web_project), 'web', skip_complexity=True, skip_duplication=True,
    )
    assert result.scan_results[0].success
    assert _score_static_scan(result) == 100
    cmd = run.call_args.args[0]
    assert cmd[0] == str(web_project / 'node_modules/.bin/eslint')
    assert '--ext' not in cmd  # flat config selects its own supported files/parsers
    assert cmd[-1] == '.'
    assert run.call_args.kwargs['cwd'] == str(web_project)
    assert run.call_args.kwargs['env']['ESLINT_USE_FLAT_CONFIG'] == 'true'
    assert 'dist/**' in cmd and 'node_modules/**' in cmd


@pytest.mark.parametrize('config', [
    '.eslintrc', '.eslintrc.json', '.eslintrc.cjs', '.eslintrc.yml', 'package.json',
])
def test_legacy_config_discovery(web_project, monkeypatch, config):
    (web_project / 'eslint.config.mjs').unlink()
    (web_project / config).write_text('{"eslintConfig": {}}' if config == 'package.json' else '{}')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, report(), ''))
    monkeypatch.setattr(collector.subprocess, 'run', run)
    assert collector.run_web_eslint(str(web_project)).success
    assert run.call_args.kwargs['env']['ESLINT_USE_FLAT_CONFIG'] == 'false'
    assert '.js,.jsx,.mjs,.cjs,.ts,.tsx,.vue' in run.call_args.args[0]


@pytest.mark.parametrize('missing', ['config', 'tool'])
def test_missing_prerequisites_are_explicit_and_not_compliant(web_project, monkeypatch, missing):
    target = 'eslint.config.mjs' if missing == 'config' else 'node_modules/.bin/eslint'
    (web_project / target).unlink()
    run = Mock()
    monkeypatch.setattr(collector.subprocess, 'run', run)
    result = collector.collect_code_quality_metrics(
        str(web_project), 'web', skip_complexity=True, skip_duplication=True,
    )
    run.assert_not_called()
    assert len(result.scan_results) == 1
    assert not result.scan_results[0].success
    assert 'Skipped:' in result.scan_results[0].error_message
    assert result.convention_compliance_rate == 0
    assert _score_static_scan(result) == 0


def test_flat_config_wins_over_legacy_and_ambient_setting(web_project, monkeypatch):
    (web_project / '.eslintrc.json').write_text('{}')
    monkeypatch.setenv('ESLINT_USE_FLAT_CONFIG', 'false')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, report(), ''))
    monkeypatch.setattr(collector.subprocess, 'run', run)
    assert collector.run_web_eslint(str(web_project)).success
    assert run.call_args.kwargs['env']['ESLINT_USE_FLAT_CONFIG'] == 'true'


def test_exit_one_retains_findings(web_project, monkeypatch):
    message = {'ruleId': 'no-undef', 'severity': 2, 'message': 'unknown is not defined', 'line': 1}
    monkeypatch.setattr(collector.subprocess, 'run', Mock(
        return_value=subprocess.CompletedProcess([], 1, report([message]), ''),
    ))
    result = collector.run_web_eslint(str(web_project))
    assert result.success and result.error_count == 1
    assert result.issues[0].rule_id == 'no-undef'


def test_exit_two_with_empty_json_is_failure(web_project, monkeypatch):
    monkeypatch.setattr(collector.subprocess, 'run', Mock(
        return_value=subprocess.CompletedProcess([], 2, '[]', 'Broken configuration'),
    ))
    result = collector.run_web_eslint(str(web_project))
    assert not result.success
    assert 'Broken configuration' in result.error_message


@pytest.mark.parametrize('output', ['', '[]', '{}', '[null]', '[{}]', 'not-json',
                                      '[{"messages":[null]}]',
                                      '[{"filePath":null,"messages":[]}]',
                                      '[{"messages":[{"severity":2,"message":"bad","ruleId":{}}]}]'])
def test_invalid_or_empty_report_is_not_a_clean_scan(web_project, monkeypatch, output):
    monkeypatch.setattr(collector.subprocess, 'run', Mock(
        return_value=subprocess.CompletedProcess([], 0, output, ''),
    ))
    result = collector.run_web_eslint(str(web_project))
    assert not result.success and result.error_message


@pytest.mark.parametrize('error', [PermissionError('not executable'),
                                  FileNotFoundError('node missing'),
                                  subprocess.TimeoutExpired('eslint', 7)])
def test_execution_failure_is_reported(web_project, monkeypatch, error):
    monkeypatch.setattr(collector.subprocess, 'run', Mock(side_effect=error))
    result = collector.run_web_eslint(str(web_project), timeout=7)
    assert not result.success and result.error_message


def test_web_complexity_and_duplication_run_tools(web_project, monkeypatch):
    run = Mock(side_effect=[
        subprocess.CompletedProcess([], 0, '<cppncss/>', ''),
        subprocess.CompletedProcess([], 0, '{"statistics":{"total":{"lines":10}}}', ''),
    ])
    monkeypatch.setattr(collector.subprocess, 'run', run)
    assert collector.run_lizard(str(web_project), 'web').success
    assert collector.run_jscpd(str(web_project), 'web').success
    assert run.call_count == 2
    assert 'jsx,tsx' in ','.join(run.call_args_list[1].args[0])


def test_miniprogram_dispatch_keeps_existing_runner(tmp_path, monkeypatch):
    run = Mock(return_value=collector.StaticScanResult(tool='eslint', success=True))
    monkeypatch.setattr(collector, 'run_eslint', run)
    result = collector.collect_code_quality_metrics(
        str(tmp_path), 'miniprogram', skip_complexity=True, skip_duplication=True,
    )
    assert result.scan_results[0].success
    run.assert_called_once_with(str(tmp_path), timeout=300)


def test_invalid_package_config_is_reported(web_project, monkeypatch):
    (web_project / 'eslint.config.mjs').unlink()
    (web_project / 'package.json').write_text('{broken')
    run = Mock()
    monkeypatch.setattr(collector.subprocess, 'run', run)
    result = collector.run_web_eslint(str(web_project))
    assert not result.success and 'package.json' in result.error_message
    run.assert_not_called()
