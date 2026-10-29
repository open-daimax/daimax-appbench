import pytest
import yaml
from evalapp.quickcheck.config import Settings
from evalapp.quickcheck.model_settings import public_model,save_model


def settings():
    s=Settings();s.model.base_url='https://gateway.example/v1';s.model.api_key='private-test-value';s.model.request_options={'enable_thinking':False,'top_p':.8}
    return s


def test_public_config_never_contains_existing_key():
    public=public_model(settings())
    assert public['credential_configured']
    assert 'api_key' not in public
    assert 'private-test-value' not in str(public)


def test_save_preserves_other_config_and_retains_blank_key(tmp_path):
    p=tmp_path/'quickcheck.yaml';original={'workspace_root':'./workspace','quickcheck':{'model':{'name':'old','request_options':{'top_p':.8}},'scoring':{'runtime_penalty_weight':.3}}}
    p.write_text(yaml.safe_dump(original));s=settings()
    public=save_model(s,p,{'name':'qwen3.8-max','base_url':'https://gateway.example/v1','api_key':'','request_options':{'temperature':0}})
    saved=yaml.safe_load(p.read_text())
    assert saved['workspace_root']==original['workspace_root']
    assert saved['quickcheck']['scoring']==original['quickcheck']['scoring']
    assert s.model.api_key=='private-test-value'
    assert 'api_key' not in saved['quickcheck']['model']
    assert saved['quickcheck']['model']['request_options']['top_p']==.8
    assert s.model.request_options['top_p']==.8
    assert 'api_key' not in public


def test_new_quickcheck_section_and_key_can_be_persisted(tmp_path):
    p=tmp_path/'quickcheck.yaml';p.write_text('# existing comment\nother: 3\n');s=settings()
    save_model(s,p,{'name':'new-model','api_key':'replacement'})
    assert yaml.safe_load(p.read_text())['quickcheck']['model']['api_key']=='replacement'
    assert '# existing comment' in p.read_text()
    assert s.model.api_key=='replacement'


@pytest.mark.parametrize('update',[{'base_url':'file:///tmp/data'},{'base_url':'https://user:password@gateway.example'},{'request_options':{'messages':[]}},{'name':''},{'request_options':{'max_tokens':-1}}])
def test_invalid_settings_do_not_change_file_or_active_model(tmp_path,update):
    p=tmp_path/'quickcheck.yaml';p.write_text('other: 3\n');s=settings();before=s.model.name
    with pytest.raises(ValueError):save_model(s,p,update)
    assert p.read_text()=='other: 3\n' and s.model.name==before
