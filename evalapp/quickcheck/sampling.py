"""Read-only readiness evidence and bounded temporal first-screen sampling."""
import asyncio
import base64
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from .frames import perceptual_hash, select_representatives

DOM_SCRIPT = r"""(tolerance) => {
 if(!document.documentElement||!document.body)return {viewport:{width:innerWidth,height:innerHeight},title:document.title,text:'',occluded_texts:[],media:0,horizontal_overflow:false,document_width:0,document_state:document.readyState,fonts_ready:false,pending_images:0,broken_images:0,loading_visible:true,meaningful:false,animated:false,layout:[],images:[],clipped_texts:[],offscreen_continuations:[],interactive_elements:[],page_scrollable:false};
 const visible=e=>{let a=e;while(a){const v=getComputedStyle(a);if(v.display==='none'||v.visibility==='hidden'||Number(v.opacity)===0)return false;a=a.parentElement}const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth&&s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)>0};
 const nodes=[...document.querySelectorAll('body *')].slice(0,10000).filter(visible);
 const leaves=nodes.filter(e=>e.children.length===0);
 const text=leaves.map(e=>e.innerText||'').join(' ').slice(0,12000);
 const images=nodes.filter(e=>e.tagName==='IMG' && e.getBoundingClientRect().width>=24 && e.getBoundingClientRect().height>=24);
 const loading=nodes.filter(e=>e.getAttribute('aria-busy')==='true'||e.getAttribute('role')==='progressbar'||(e.children.length===0&&/^(加载中[.。…]*|正在加载[.。…]*|loading[. …]*|please wait[. …]*)$/i.test((e.innerText||'').trim())));
 const rect=e=>{const r=e.getBoundingClientRect();return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]};
 const occluded=leaves.filter(e=>(e.innerText||'').trim()).filter(e=>{const r=e.getBoundingClientRect();const top=document.elementFromPoint(Math.max(0,Math.min(innerWidth-1,r.x+r.width/2)),Math.max(0,Math.min(innerHeight-1,r.y+r.height/2)));return top&&!e.contains(top)&&!top.contains(e)}).map(e=>e.innerText.trim()).slice(0,100);
 const rootStyle=getComputedStyle(document.documentElement),bodyStyle=getComputedStyle(document.body);
 const scrollContainers=nodes.filter(e=>{const s=getComputedStyle(e);return (['auto','scroll'].includes(s.overflowY)&&e.scrollHeight>e.clientHeight+2)||(['auto','scroll'].includes(s.overflowX)&&e.scrollWidth>e.clientWidth+2)});
 const rootScrollable=document.documentElement.scrollHeight>innerHeight+tolerance&&!['hidden','clip'].includes(rootStyle.overflowY)&&!['hidden','clip'].includes(bodyStyle.overflowY);
 const scrollable=rootScrollable||scrollContainers.length>0;
 const belowFold=leaves.filter(e=>(e.innerText||'').trim()).filter(e=>{const r=e.getBoundingClientRect();return rootScrollable&&r.bottom>innerHeight||scrollContainers.some(n=>{const nr=n.getBoundingClientRect();return n.contains(e)&&(r.bottom>nr.bottom||r.top<nr.top||r.right>nr.right||r.left<nr.left)})}).map(e=>e.innerText.trim());
 const clipped=leaves.filter(e=>(e.innerText||'').trim()).filter(e=>{let n=e;const tr=e.getBoundingClientRect();while(n&&n!==document.documentElement){const s=getComputedStyle(n),r=n.getBoundingClientRect();if(n!==e&&scrollContainers.includes(n))return false;if((['hidden','clip'].includes(s.overflowX)&&(tr.left<r.left-2||tr.right>r.right+2||n===e&&e.scrollWidth>e.clientWidth+2))||(['hidden','clip'].includes(s.overflowY)&&(tr.top<r.top-2||tr.bottom>r.bottom+2||n===e&&e.scrollHeight>e.clientHeight+2)))return true;n=n.parentElement}return false}).map(e=>e.innerText.trim());
 const media=nodes.filter(e=>['IMG','CANVAS','VIDEO','SVG','IFRAME'].includes(e.tagName)).length;
 const inAnimation=e=>{let n=e;while(n&&n!==document.body){if(getComputedStyle(n).animationName!=='none')return true;n=n.parentElement}return false};
 const movingText=e=>{let a=e;while(a&&a!==document.body){if(a.tagName==='MARQUEE')return true;try{if(a.getAnimations().some(animation=>animation.effect&&animation.effect.getKeyframes().some(k=>k.transform&&k.transform!=='none'||k.translate||k.left||k.right)))return true}catch{}a=a.parentElement}return false};
 const animatedTexts=leaves.filter(e=>(e.innerText||'').trim()&&movingText(e)).map(e=>e.innerText.trim());
 const controls=nodes.filter(e=>['BUTTON','A','INPUT','SELECT','TEXTAREA'].includes(e.tagName)||e.getAttribute('role')==='button').slice(0,80).map(e=>{const r=e.getBoundingClientRect();const top=document.elementFromPoint(Math.max(0,Math.min(innerWidth-1,r.x+r.width/2)),Math.max(0,Math.min(innerHeight-1,r.y+r.height/2)));return {text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').trim(),rect:rect(e),scroll_continuation:scrollContainers.some(n=>n.contains(e)),center_unoccluded:r.x+r.width/2>=0&&r.x+r.width/2<innerWidth&&r.y+r.height/2>=0&&r.y+r.height/2<innerHeight&&!!top&&(e.contains(top)||top.contains(e))}});
 return {animated_texts:animatedTexts,scroll_containers:scrollContainers.slice(0,20).map(e=>({rect:rect(e),scroll_height:e.scrollHeight,client_height:e.clientHeight})),interactive_elements:controls,page_scrollable:scrollable,offscreen_continuations:scrollable?belowFold:[],clipped_texts:clipped,viewport:{width:innerWidth,height:innerHeight},title:document.title,text,occluded_texts:occluded,media,
 document_width:document.documentElement.scrollWidth,
 horizontal_overflow:document.documentElement.scrollWidth>innerWidth+tolerance,
 document_state:document.readyState, fonts_ready:!document.fonts||document.fonts.status==='loaded',
 pending_images:images.filter(e=>!e.complete).length, broken_images:images.filter(e=>e.complete&&e.naturalWidth===0).length,
 loading_visible:loading.length>0, meaningful:!!text.trim()||media>0,
 animated:nodes.some(e=>getComputedStyle(e).animationName!=='none')||nodes.some(e=>['CANVAS','VIDEO'].includes(e.tagName)),
 layout:leaves.filter(e=>!inAnimation(e)).filter(e=>/[\p{L}\p{N}]/u.test(e.innerText||'')||['IMG','CANVAS','VIDEO','INPUT','BUTTON','A'].includes(e.tagName)).slice(0,150).map(e=>[e.tagName,...rect(e)]),
 images:images.slice(0,50).map(e=>({rect:rect(e),loaded:e.complete&&e.naturalWidth>0}))};
}"""

def frame_stats(path, previous=None):
    with Image.open(path) as source:
        image=source.convert('RGB').resize((96,96))
        stddev=max(ImageStat.Stat(image).stddev)
        delta=None
        if previous:
            with Image.open(previous) as old:
                diff=ImageChops.difference(image,old.convert('RGB').resize((96,96)))
                delta=sum(ImageStat.Stat(diff).mean)/(3*255)
    return stddev,delta


def ready_decision(samples, settings, *, expired=False):
    """Pure decision: absence of evidence is never a successful rendering."""
    if not samples:
        return 'unsettled'
    tail=samples[-settings.stable_samples:]
    if len(tail)<settings.stable_samples:
        return 'unsettled'
    def ready(s):
        captured=(expired or samples[-1].get('elapsed_ms',0)>=settings.minimum_observation_seconds*1000) and s.get('capture_method') in {'playwright','chromium_compositor'}
        dom=s['dom']
        # DOMContentLoaded plus repeated captured pixels can be inspectable while
        # noncritical fonts/subresources still delay the window load event.
        return (dom['document_state']=='complete' or captured and dom['document_state']=='interactive') and (dom['fonts_ready'] or captured) and not dom['pending_images'] and not s['pending_critical']
    if not all(ready(s) for s in tail):
        return 'unsettled'
    if all(s['dom']['loading_visible'] for s in tail):
        return 'persistent_loading' if expired else 'unsettled'
    blank=all(not s['dom']['meaningful'] and s['stddev']<settings.blank_pixel_stddev for s in tail)
    if blank:
        return 'confirmed_blank_screen' if expired else 'unsettled'
    if all(s['stddev']<settings.blank_pixel_stddev and not s['dom']['text'].strip() for s in tail):
        # A canvas/DOM node alone cannot prove that visible content was rendered.
        return 'unsettled'
    if not all(s['dom']['meaningful'] for s in tail):
        return 'unsettled'
    layouts=[s['dom']['layout'] for s in tail]
    def close_layout(layout):
        reference=layouts[0]
        return len(layout)==len(reference) and all(a[0]==b[0] and all(abs(x-y)<=settings.layout_tolerance_pixels for x,y in zip(a[1:],b[1:])) for a,b in zip(layout,reference))
    same_layout=all(close_layout(layout) for layout in layouts)
    same_text=all(s['dom']['text']==tail[0]['dom']['text'] for s in tail)
    stable_pixels=all(s['delta'] is not None and s['delta']<=settings.frame_change_threshold for s in tail[1:])
    if same_layout and same_text and stable_pixels:
        return 'stable'
    if same_layout and all(s['dom']['animated'] for s in tail):
        return 'animated_content'
    return 'unsettled'


async def screenshot(context, page, path, timeout, *, is_mobile=False):
    """Use Playwright's viewport-aware capture, with explicit geometry checks."""
    before=await page.evaluate('({width:innerWidth,height:innerHeight})')
    method='playwright'
    use_compositor=getattr(page,'_quickcheck_capture_session',None) is not None
    if not use_compositor:
        try:
            await page.screenshot(path=str(path),full_page=False,timeout=timeout*1000)
        except Exception as exc:
            if 'waiting for fonts' not in str(exc) or before!=page.viewport_size:
                raise
            use_compositor=True
    if use_compositor:
        # Font downloads may remain pending after readable fallback text is painted.
        # Only recover this specific failure; preserve the configured CSS viewport.
        session=getattr(page,'_quickcheck_capture_session',None)
        if session is None:
            session=await context.new_cdp_session(page)
            page._quickcheck_capture_session=session
        # Keep the session alive until context.close(): detaching clears device
        # metrics globally, including those owned by Playwright's page session.
        await asyncio.wait_for(session.send('Emulation.setDeviceMetricsOverride',{'width':before['width'],'height':before['height'],'screenWidth':before['width'],'screenHeight':before['height'],'deviceScaleFactor':1,'mobile':is_mobile}),timeout=timeout)
        data=await asyncio.wait_for(session.send('Page.captureScreenshot',{
            'format':'png','fromSurface':True,'captureBeyondViewport':False}),timeout=timeout)
        path.write_bytes(base64.b64decode(data['data']))
        method='chromium_compositor'
    after=await page.evaluate('({width:innerWidth,height:innerHeight})')
    if before!=after:
        raise ValueError(f'screenshot_changed_layout_viewport: {before} -> {after}')
    viewport=page.viewport_size
    with Image.open(path) as image:
        if image.size!=(viewport['width'],viewport['height']):
            raise ValueError('screenshot_viewport_mismatch')
    return method


async def observe(context,page,device,output,settings,pending):
    started=time.monotonic()
    samples=[]
    state='unsettled'
    while True:
        dom=await asyncio.wait_for(page.evaluate(DOM_SCRIPT,settings.overflow_tolerance_pixels),timeout=3)
        path=output/f'{device}-frame-{len(samples):02}.png'
        try:
            capture_method=await screenshot(context,page,path,settings.screenshot_seconds,is_mobile=device=='mobile')
        except Exception as exc:
            if 'Timeout' in type(exc).__name__ and time.monotonic()-started<settings.readiness_seconds:
                await asyncio.sleep(min(1,settings.sample_interval_seconds))
                continue
            raise
        stddev,delta=frame_stats(path,output/samples[-1]['screenshot'] if samples else None)
        samples.append({'elapsed_ms':round((time.monotonic()-started)*1000),'dom':dom,
            'screenshot':path.name,'stddev':round(stddev,4),'delta':round(delta,5) if delta is not None else None,
            'capture_method':capture_method,'pending_critical':len(pending),'phash':perceptual_hash(path)})
        elapsed=time.monotonic()-started
        expired=elapsed>=settings.readiness_seconds
        state=ready_decision(samples,settings,expired=expired)
        if expired or (elapsed>=settings.minimum_observation_seconds and state in ('stable','animated_content')):
            break
        await asyncio.sleep(min(settings.sample_interval_seconds,max(.01,settings.readiness_seconds-elapsed)))
    selected=samples[-1]
    (output/f'{device}.png').write_bytes((output/selected['screenshot']).read_bytes())
    (output/f'{device}-early.png').write_bytes((output/samples[0]['screenshot']).read_bytes())
    representatives,duplicates=select_representatives(samples,output,settings)
    return samples, {'state':state,'scorable':state in ('stable','animated_content'),
        'observed_ms':round((time.monotonic()-started)*1000),'sample_count':len(samples),
        'selected_screenshot':selected['screenshot'],'fonts_pending':not selected['dom']['fonts_ready'],'capture_method':selected.get('capture_method','playwright'),
        'model_screenshots':[s['screenshot'] for s in representatives],
        'deduplication':{'method':'phash64+pixel+local+semantic','sample_count':len(samples),'candidate_count':min(len(samples),settings.stable_samples),'near_duplicates':duplicates,'model_frame_count':len(representatives)},
        'reason':'Ready in repeated observations.' if state in ('stable','animated_content') else 'Content did not become reliably scorable within the observation budget.'}
