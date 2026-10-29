"""Local model preferences. Existing credentials are never returned to the browser."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import yaml
from .config import ModelConfig


def public_model(settings):
    model=settings.model
    return {'name':model.name,'base_url':model.base_url,'api_key_env':model.api_key_env,
            'credential_configured':bool(model.api_key or os.environ.get(model.api_key_env)),
            'request_options':{k:v for k,v in model.request_options.items() if k in ('temperature','max_tokens','enable_thinking')}}


def save_model(settings, path, update):
    allowed={'name','base_url','api_key_env','api_key','request_options'}
    if not isinstance(update,dict) or set(update)-allowed:raise ValueError('unsupported_model_field')
    if 'request_options' in update and (not isinstance(update['request_options'],dict) or set(update['request_options'])-{'temperature','max_tokens','enable_thinking'}):raise ValueError('unsupported_request_options')
    values={**settings.model.model_dump(), 'api_key':settings.model.api_key, **update}
    values['request_options']={**settings.model.request_options,**update.get('request_options',{})}
    if not values.get('api_key'):values['api_key']=settings.model.api_key
    if not isinstance(values.get('name'),str) or not values['name'].strip():raise ValueError('model_name_required')
    parsed=urlsplit(values.get('base_url',''))
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise ValueError('invalid_model_base_url')
    if 'temperature' in update.get('request_options',{}) and (not isinstance(update['request_options']['temperature'],(int,float)) or not 0<=update['request_options']['temperature']<=2):raise ValueError('invalid_temperature')
    if 'max_tokens' in update.get('request_options',{}) and (not isinstance(update['request_options']['max_tokens'],int) or isinstance(update['request_options']['max_tokens'],bool) or not 512<=update['request_options']['max_tokens']<=32000):raise ValueError('invalid_max_tokens')
    if 'enable_thinking' in update.get('request_options',{}) and not isinstance(update['request_options']['enable_thinking'],bool):raise ValueError('invalid_thinking')
    model=ModelConfig.model_validate(values)
    path=Path(path);text=path.read_text() if path.exists() else ''
    try:data=yaml.safe_load(text) or {}
    except yaml.YAMLError:raise ValueError('invalid_configuration') from None
    if not isinstance(data,dict):raise ValueError('invalid_configuration')
    quick=dict(data.get('quickcheck') or {});stored=dict(quick.get('model') or {})
    options={**(stored.get('request_options') or {}),**update.get('request_options',{})}
    stored.update({k:v for k,v in update.items() if k!='api_key' or v})
    if 'request_options' in update:stored['request_options']=options
    quick['model']=stored
    tree=yaml.compose(text);node=next((v for k,v in tree.value if k.value=='quickcheck'),None) if isinstance(tree,yaml.MappingNode) else None
    encoded=json.dumps(quick,ensure_ascii=False)
    if node is None:new=text.rstrip()+'\n\nquickcheck: '+encoded+'\n'
    else:
        tail='\n'+' '*node.end_mark.column if isinstance(node,yaml.MappingNode) and not node.flow_style else ''
        new=text[:node.start_mark.index]+encoded+tail+text[node.end_mark.index:]
    expected={**data,'quickcheck':quick}
    if yaml.safe_load(new)!=expected:raise ValueError('configuration_roundtrip_failed')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
            temp=f.name;f.write(new)
        os.chmod(temp,path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(temp,path);temp=None
    finally:
        if temp:Path(temp).unlink(missing_ok=True)
    settings.model=model
    return public_model(settings)
