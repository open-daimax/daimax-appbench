"""Browser lifecycle and first-screen evidence collection."""
import asyncio
import hashlib
from urllib.parse import urlparse
from .sampling import observe

def clipped_controls(final):
    viewport=final.get('viewport',{})
    width=viewport.get('width',0);height=viewport.get('height',0)
    found=[]
    excluded=set(final.get('inactive_texts',[]))|set(final.get('animated_texts',[]))|(set(final.get('offscreen_continuations',[]))-set(final.get('clipped_texts',[])))
    for c in final.get('interactive_elements',[]):
        rect=c.get('rect',[])
        if len(rect)!=4 or not c.get('text') or c.get('scroll_continuation') or c.get('text') in excluded:continue
        x,y,w,h=rect
        if w<=0 or h<=0:continue
        fraction=max(0,min(width,x+w)-max(0,x))*max(0,min(height,y+h)-max(0,y))/(w*h)
        if 0<fraction<.75 and not (0<=x+w/2<width and 0<=y+h/2<height):
            found.append({'text':c['text'],'rect':rect,'visible_fraction':round(fraction,3)})
    return found


def navigation_readiness(readiness, final, timed_out):
    """A navigation event timeout must not veto repeated, meaningful visual readiness."""
    result=dict(readiness)
    if not timed_out:return result
    result['navigation_timed_out']=True
    visually_ready=(result.get('scorable') is True and result.get('sample_count',0)>=2 and final.get('meaningful') is True and not final.get('loading_visible'))
    if visually_ready:
        result['navigation_note']='Navigation event timed out; repeated rendered observations are ready.'
    elif final.get('document_state')!='complete' and result.get('state') not in {'confirmed_blank_screen','persistent_loading'}:
        result.update(state='unsettled',scorable=False,reason='Navigation timed out before observable readiness.')
    return result


async def capture(browser, device, viewport, url, output, settings):
    context=await browser.new_context(viewport=viewport, is_mobile=device=='mobile', has_touch=device=='mobile', device_scale_factor=1)
    page=await context.new_page()
    errors=[]; failures=[]; console_errors=[]; pending=set()
    def request_started(request):
        if request.resource_type in ('document','script','stylesheet','xhr','fetch'):
            pending.add(request)
    def request_finished(request):
        pending.discard(request)
    def request_failed(request):
        pending.discard(request)
        if request.failure!='net::ERR_ABORTED':
            failures.append({'request_id':hashlib.sha256(request.url.encode()).hexdigest()[:20],'status':None,'type':request.resource_type,'same_origin':urlparse(request.url).netloc==urlparse(url).netloc})
    page.on('request',request_started)
    page.on('requestfinished',request_finished)
    page.on('requestfailed',request_failed)
    page.on('console',lambda msg:console_errors.append(msg.text[:1000]) if msg.type=='error' else None)
    page.on('pageerror',lambda e:errors.append(str(e)[:1000]))
    page.on('response',lambda r:failures.append({'request_id':hashlib.sha256(r.url.encode()).hexdigest()[:20],'status':r.status,'type':r.request.resource_type,'same_origin':urlparse(r.url).netloc==urlparse(url).netloc}) if r.status>=400 else None)
    try:
        navigation_timed_out=False
        try:
            response=await page.goto(url,wait_until='domcontentloaded',timeout=settings.navigation_seconds*1000)
        except Exception as exc:
            if 'Timeout' in type(exc).__name__:
                response=None
                navigation_timed_out=True
            else:
                return {'device':device,'open_failed':True,'error':'navigation_failed'}
        if response and response.status>=400:
            return {'device':device,'open_failed':True,'http_status':response.status}
        samples,readiness=await observe(context,page,device,output,settings,pending)
        early=samples[0]['dom']; final=samples[-1]['dom']
        readiness=navigation_readiness(readiness,final,navigation_timed_out)
        return {'device':device,'open_failed':False,'early':early,'final':final,'samples':samples,'readiness':readiness,'errors':errors[:20],'resource_failures':failures[:20],'console_errors':console_errors[:20]}
    finally:
        try:
            await asyncio.wait_for(context.close(),timeout=settings.cleanup_seconds)
        except asyncio.TimeoutError:
            pass  # The owning browser/driver cleanup is the final resource boundary.
