"""Configuration changes must reach scoring, snapshots and frontend rules together."""
import pytest
from pydantic import ValidationError
from evalapp.quickcheck.config import Settings
from evalapp.quickcheck.scoring_config import ScoringSettings
from evalapp.quickcheck.policy import resolve_scoring,policy_document,scoring_rules,judgment_prompt
from evalapp.quickcheck.score_worker import score_assessment
from tests.test_quickcheck_scoring import fixture,item


def test_custom_weights_anchors_and_runtime_coefficient_are_used():
    settings=Settings()
    settings.scoring.overall_weights={'visual':.2,'information':.5,'adaptation':.3}
    settings.scoring.quality_anchors['competent']=65
    settings.scoring.runtime_penalty_weight=.5
    a,t=fixture()
    for row in a['items']:row['quality'].update(execution='competent',refinements=[])
    policy=policy_document(settings)
    scored=score_assessment(a,t,policy)
    assert item(scored,'typography')['score']==65
    assert scored['overall_weights']=={'visual':.2,'information':.5,'adaptation':.3}
    assert scored['overall_breakdown']['runtime_penalty_weight']==.5
    assert scoring_rules(settings)['quality_anchors']['competent']==65
    assert 'competent=65' in judgment_prompt(settings)


def test_item_weight_and_checkpoint_penalties_are_configurable():
    settings=Settings()
    settings.scoring.item_weights.update(composition=.10,creative_expression=.40)
    settings.scoring.checkpoint_deductions={'partial':12,'no':25}
    a,t=fixture();a['items'][0]['checks'][0]['verdict']='partial'
    rules=resolve_scoring(settings)
    scored=score_assessment(a,t,rules)
    assert item(scored,'composition')['weight']==.10
    assert item(scored,'composition')['score']==88


def test_policy_is_a_frozen_copy_of_configuration():
    settings=Settings();saved=policy_document(settings)
    settings.scoring.quality_anchors['competent']=65
    assert saved['quality_anchors']['competent']==60
    assert resolve_scoring(settings)['quality_anchors']['competent']==65


@pytest.mark.parametrize('values',[
    {'overall_weights':{'visual':.9,'information':.3,'adaptation':.2}},
    {'overall_weights':{'visual':1}},
    {'runtime_penalty_weight':1.2},
    {'quality_anchors':{'weak':35,'basic':50,'competent':60,'considered':70,'refined':85,'exceptional':100}},
    {'typo_key':3},
])
def test_invalid_configuration_is_rejected(values):
    with pytest.raises(ValidationError):ScoringSettings.model_validate(values)


def test_default_overall_weights_are_four_three_three():
    settings=Settings()
    assert settings.scoring.overall_weights=={'visual':.4,'information':.3,'adaptation':.3}
    assert policy_document(settings)['overall_weights']==scoring_rules(settings)['overall_weights']


def test_yaml_roundtrip_keeps_prompt_and_fingerprint_identical():
    import yaml
    from evalapp.quickcheck.config import ApplicationConfig
    implicit = Settings()
    explicit = ApplicationConfig.model_validate(yaml.safe_load(yaml.safe_dump(
        {'quickcheck': implicit.model_dump()}, sort_keys=False))).quickcheck
    assert implicit.scoring.model_dump() == explicit.scoring.model_dump()
    assert judgment_prompt(implicit) == judgment_prompt(explicit)
    assert policy_document(implicit)['prompt_sha256'] == policy_document(explicit)['prompt_sha256']
