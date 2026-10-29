"""Model selection follows explicit QuickCheck configuration, not a default name."""
from evalapp.config import Config
from evalapp.commands.quickcheck import settings_from_config


def test_explicit_quickcheck_slot_model_is_not_replaced_by_default():
    config=Config(models={'quickcheck':{'name':'custom-vision','base_url':'https://gateway.example/v1','api_key':'test-only'}})
    settings=settings_from_config(config)
    assert settings.model.name=='custom-vision'
    assert settings.model.base_url=='https://gateway.example/v1'
    assert settings.model.api_key=='test-only'


def test_quickcheck_model_section_takes_precedence_over_slot_name():
    config=Config(models={'quickcheck':{'name':'slot-model'}},quickcheck={'model':{'name':'chosen-model'}})
    assert settings_from_config(config).model.name=='chosen-model'


def test_default_model_is_preserved_when_no_slot_is_selected():
    assert settings_from_config(Config()).model.name=='qwen3.8-flash'
