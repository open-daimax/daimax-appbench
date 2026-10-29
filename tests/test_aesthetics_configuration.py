"""Provider routing must be explicit and consistent across scoring entry points."""
import json
import logging
from pathlib import Path

import httpx
import pytest

from evalapp.config import Config
from evalapp.evaluation.metrics.collectors import aesthetics, aesthetics_scorer
from evalapp.evaluation.metrics.collectors.aesthetics_scorer import ModelConfig
from evalapp.services.aesthetics import _build_model_config


@pytest.fixture(autouse=True)
def isolated_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ('AESTHETICS_BASE_URL', 'AESTHETICS_MODEL', 'AESTHETICS_API_KEY', 'DASHSCOPE_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr('evalapp.config.get_config', lambda: Config())


def test_unconfigured_slot_does_not_select_a_provider() -> None:
    slot = Config().models.aesthetics
    assert slot.base_url == ''
    assert slot.name == ''


@pytest.mark.parametrize('entry', ['explicit', 'implicit', 'collector'])
def test_environment_is_respected_by_each_entry_point(entry: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('AESTHETICS_BASE_URL', 'https://vision.example/v1')
    monkeypatch.setenv('AESTHETICS_MODEL', 'custom-vision')
    monkeypatch.setenv('AESTHETICS_API_KEY', 'test-generic-key')
    model = (aesthetics._default_model_config() if entry == 'collector'
             else _build_model_config(Config() if entry == 'explicit' else None))
    assert (model.base_url, model.name, model.api_key) == (
        'https://vision.example/v1', 'custom-vision', 'test-generic-key')


def test_explicit_config_and_model_override_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('AESTHETICS_BASE_URL', 'https://env.example/v1')
    monkeypatch.setenv('AESTHETICS_MODEL', 'env-model')
    monkeypatch.setenv('AESTHETICS_API_KEY', 'env-key')
    config = Config(models={'aesthetics': {'base_url': 'https://config.example/v1',
                                         'name': 'config-model', 'api_key': 'config-key'}})
    model = _build_model_config(config, model_name='override-model')
    assert (model.base_url, model.name, model.api_key) == (
        'https://config.example/v1', 'override-model', 'config-key')


def test_legacy_key_is_supported_without_selecting_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'legacy-test-key')
    model = _build_model_config(Config())
    assert model.api_key == 'legacy-test-key'
    assert model.base_url == '' and model.name == ''
    monkeypatch.setenv('AESTHETICS_API_KEY', 'generic-test-key')
    assert _build_model_config(Config()).api_key == 'generic-test-key'


@pytest.mark.parametrize('base_url,name', [('', ''), ('', 'model'), ('https://vision.example/v1', '')])
def test_incomplete_configuration_warns_and_skips_without_model_call(
    base_url: str, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame = tmp_path/'frame.png'
    monkeypatch.setattr(aesthetics, 'select_key_frames', lambda *args: [frame])
    def unexpected_call(*args: object) -> None:
        pytest.fail('Unconfigured aesthetics must not make a model request')
    monkeypatch.setattr(aesthetics, 'score_frames', unexpected_call)
    with caplog.at_level(logging.WARNING):
        result = aesthetics.score_aesthetics(str(tmp_path), 'web', model_config=ModelConfig(
            base_url=base_url, name=name, api_key='PRIVATE_TEST_SENTINEL'))
    assert result is None
    assert 'skipped' in caplog.text.lower()
    assert 'AESTHETICS_BASE_URL' in caplog.text and 'AESTHETICS_MODEL' in caplog.text
    assert 'PRIVATE_TEST_SENTINEL' not in caplog.text
    trace = json.loads((tmp_path/'aesthetics_trace_web.json').read_text())
    assert trace['status'] == 'skipped'
    assert trace['skip_reason'] == 'model_not_configured'
    assert 'PRIVATE_TEST_SENTINEL' not in json.dumps(trace)


def test_direct_scorer_rejects_missing_endpoint_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(aesthetics_scorer, '_call_api', lambda *args: calls.append(1))
    monkeypatch.setattr(aesthetics_scorer.time, 'sleep', lambda *args: None)
    with pytest.raises(ValueError, match='base_url'):
        aesthetics_scorer.score_frames([], '', ModelConfig(name='model'))
    assert calls == []


@pytest.mark.parametrize('key', ['', 'configured-test-key'])
def test_explicit_local_endpoint_supports_optional_authentication(
    key: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}], 'usage': {}})
    original_client = httpx.Client
    monkeypatch.setattr(aesthetics_scorer.httpx, 'Client',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    aesthetics_scorer._call_api([], ModelConfig(base_url='http://127.0.0.1:11434/v1',
                                               name='local-vision', api_key=key))
    assert str(requests[0].url) == 'http://127.0.0.1:11434/v1/chat/completions'
    assert requests[0].headers.get('Authorization') == ('Bearer '+key if key else None)


def test_credential_alone_never_selects_or_calls_a_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'PRIVATE_TEST_SENTINEL')
    monkeypatch.setattr(aesthetics, 'select_key_frames', lambda *args: [tmp_path/'frame.png'])
    def unexpected_call(*args: object) -> None:
        pytest.fail('A credential alone must not send screenshots to a default provider')
    monkeypatch.setattr(aesthetics, 'score_frames', unexpected_call)
    with caplog.at_level(logging.WARNING):
        assert aesthetics.score_aesthetics(str(tmp_path), 'web') is None
    assert 'skipped' in caplog.text.lower()
    assert 'PRIVATE_TEST_SENTINEL' not in caplog.text
