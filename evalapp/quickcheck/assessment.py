"""Multimodal evidence input and bounded JSON model transport."""
import base64
import asyncio
import json
import os
import time
import httpx
from .browser import clipped_controls


def selected_samples(capture):
    samples=capture['samples']
    names=capture.get('readiness',{}).get('model_screenshots')
    if names is not None:
        return [s for s in samples if s['screenshot'] in names]
    return samples[-2:] if capture.get('readiness',{}).get('state')=='animated_content' else samples[-1:]

def messages(captures, output):
    observations = {}; images = []
    for device in ('mobile', 'desktop'):
        if device not in captures:
            continue
        capture = captures[device]; final = capture['final']
        excluded = set(final.get('occluded_texts', [])) | set(final.get('animated_texts', [])) | (set(final.get('offscreen_continuations', [])) - set(final.get('clipped_texts', [])))
        keys = ('viewport', 'document_width', 'horizontal_overflow', 'page_scrollable', 'document_state', 'fonts_ready', 'pending_images', 'loading_visible')
        facts = {key: final[key] for key in keys if key in final}
        facts['interactive_elements'] = [item for item in final.get('interactive_elements', []) if item.get('text') not in excluded]
        facts['clipped_texts'] = [text for text in final.get('clipped_texts', []) if text not in excluded]
        facts['clipped_controls'] = clipped_controls(final)
        facts['excluded_background_or_scroll_controls'] = sum(item.get('text') in excluded for item in final.get('interactive_elements', []))
        observations[device] = {'readiness': capture.get('readiness'), 'final': facts}
        for sample in selected_samples(capture):
            path = output / sample['screenshot']
            images.extend([{'type': 'text', 'text': f'{device}: {path.name}'},
                           {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode(), 'detail': 'high'}}])
    return [{'type': 'text', 'text': 'Measured active-scope facts. Background/scroll continuations are excluded from controls; inspect only the active screenshot layer. A hit-test flag is not proof that a rectangle fits the viewport. Do not infer missing sidebar or interaction success. ' + json.dumps(observations, ensure_ascii=False, sort_keys=True)}, *images]

class ModelRequestError(ValueError):
    def __init__(self, code, transport):
        super().__init__(code)
        self.model_transport = transport

class ModelProtocolError(ModelRequestError):
    pass

def model_document(response):
    """Adapt unambiguous JSON shapes, preserving every returned judgment."""
    try:
        envelope=response.json()
        choice=envelope['choices'][0]
        message=choice['message']
    except (ValueError,KeyError,IndexError,TypeError):
        raise ValueError('invalid_model_envelope') from None
    info={'usage':envelope.get('usage'),'finish_reason':choice.get('finish_reason')}
    if message.get('refusal') or choice.get('finish_reason')=='content_filter':
        raise ValueError('model_content_filtered')
    text=message.get('content')
    if isinstance(text,list) and all(isinstance(part,dict) and part.get('type')=='text' and isinstance(part.get('text'),str) for part in text):
        text=''.join(part['text'] for part in text)
    info['content_type']=type(text).__name__
    info['model_output']=text[:16000] if isinstance(text,str) else None
    if not isinstance(text,str) or not text.strip():
        return None,{**info,'code':'invalid_model_content'}
    text=text.strip()
    if text.startswith('```') and '\n' in text:
        text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
    try:data=json.loads(text)
    except (ValueError,TypeError):return None,{**info,'code':'invalid_model_json'}
    info['root_type']=type(data).__name__
    if isinstance(data,list):
        if len(data)==1 and isinstance(data[0],dict) and any(k in data[0] for k in ('items','quality','patches','compliance')):
            data=data[0];info['adapter']='single_root_object_array'
        elif data and all(isinstance(row,dict) and isinstance(row.get('path'),list) and 'value' in row for row in data):
            data={'patches':data};info['adapter']='patch_rows_array'
        elif data and all(isinstance(row,dict) for row in data):
            from .policy import ITEMS,COMPLIANCE
            item_rows=[row for row in data if row.get('id') in ITEMS]
            content_rows=[row for row in data if row.get('id') in COMPLIANCE]
            adjustment_rows=[row for row in data if row.get('kind') in ('bonus','deduction') and row.get('rule_id')]
            if len(item_rows)+len(content_rows)+len(adjustment_rows)==len(data) and item_rows:
                data={'items':item_rows,'compliance':content_rows,'adjustments':adjustment_rows};info['adapter']='assessment_rows_array'
    if not isinstance(data,dict) or not data:
        return None,{**info,'code':'invalid_model_response'}
    return data,info

async def request_json(client, settings, content, instruction, *, system_prompt=None, attempt_recorder=None):
    if system_prompt is None:
        from .judge import SYSTEM
        system_prompt = SYSTEM
    model=settings.model
    key=os.environ.get(model.api_key_env) or model.api_key
    if not key or not model.name or not model.base_url:raise ValueError('model_not_configured')
    options={k:v for k,v in model.request_options.items() if k not in ('model','messages','stream')}
    payload={'model':model.name,'messages':[{'role':'system','content':system_prompt},
              {'role':'user','content':[{'type':'text','text':instruction},*content]}],
             'temperature':0,'max_tokens':8000,
             'response_format':{'type':'json_object'},**options}
    read_timeout=client.timeout.read
    budget=min(settings.model_seconds,read_timeout if read_timeout is not None else settings.model_seconds)
    deadline=time.monotonic()+budget;retry_events=[];protocol_events=[];attempt_usage=[];format_retried=False
    for attempt in range(settings.model_max_retries+1):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise asyncio.TimeoutError()
        response=None;attempt_started=time.monotonic();code=None
        def record_attempt(**details):
            if attempt_recorder is not None:
                attempt_recorder({'attempt':attempt+1,'duration_ms':round((time.monotonic()-attempt_started)*1000),**details})
        try:
            response=await client.post(model.base_url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload,timeout=remaining)
        except httpx.TransportError as exc:
            code=type(exc).__name__;record_attempt(status='transport_error',error=code)
            if attempt>=settings.model_max_retries:
                exc.model_transport={'attempts':attempt+1,'retry_events':retry_events,'protocol_events':protocol_events,'terminal_error':code}
                raise
        else:
            if response.status_code==200:
                try:data,info=model_document(response)
                except ValueError as exc:data=None;info={'code':str(exc)}
                if info.get('usage'):attempt_usage.append(info['usage'])
                if data is not None:
                    record_attempt(status='response',http_status=200,finish_reason=info.get('finish_reason'),adapter=info.get('adapter'))
                    data['_transport']={'attempts':attempt+1,'retry_events':retry_events,'protocol_events':protocol_events,
                                        'usage':info.get('usage'),'attempt_usage':attempt_usage,'finish_reason':info.get('finish_reason'),'adapter':info.get('adapter')}
                    return data
                code=info['code'];protocol_events.append({k:v for k,v in info.items() if k!='model_output'})
                record_attempt(status='protocol_error',http_status=200,**info)
                transport={'attempts':attempt+1,'retry_events':retry_events,'protocol_events':protocol_events,'attempt_usage':attempt_usage,'terminal_error':code}
                if format_retried or attempt>=settings.model_max_retries or code=='model_content_filtered':
                    raise ModelProtocolError(code,transport)
                format_retried=True
                retry_events.append({'attempt':attempt+1,'error':code,'delay_ms':0,'kind':'empty_or_unparseable_output'})
                payload['messages'].append({'role':'user','content':'上次没有返回可用JSON对象。请严格按原任务返回根为对象的JSON，不要根数组、null或Markdown；保留原任务所要求的字段。'})
                continue
            code='model_http_'+str(response.status_code)
            record_attempt(status='response',http_status=response.status_code)
            if response.status_code not in (408,429,500,502,503,504) or attempt>=settings.model_max_retries:
                raise ModelRequestError(code,{'attempts':attempt+1,'retry_events':retry_events,'terminal_error':code})
        delay=min(8.,settings.model_retry_backoff_seconds*(2**attempt))
        if response is not None:
            try:delay=min(8.,max(delay,float(response.headers.get('Retry-After','0'))))
            except (ValueError,TypeError):pass
        if delay>=deadline-time.monotonic():raise asyncio.TimeoutError()
        retry_events.append({'attempt':attempt+1,'error':code,'delay_ms':round(delay*1000)})
        await asyncio.sleep(delay)
    raise ModelRequestError('model_request_exhausted',{'retry_events':retry_events})
