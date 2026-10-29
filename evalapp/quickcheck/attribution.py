"""Conservative matching for explicitly shared device-scale complaints."""
import re


def scale_loss(text):
    return bool(re.search(r'偏小|过小|太小|尺度|缩放|过窄|狭窄|留白|空白|尺寸.*(?:不足|小|未|不适)|未.*放大|too small|undersized|narrow',str(text),re.I))

def device_scale_claim(text):
    return any(re.search(r'桌面|宽屏|PC|desktop',clause,re.I) and scale_loss(clause) for clause in re.split(r'[，,；;。]',str(text)))


def shared_desktop_loss(owner, row, items):
    if owner in {'desktop','mobile','creative_expression'}:return False
    desktop=next((r for r in items if isinstance(r,dict) and r.get('id')=='desktop'),{})
    def reason(r):
        q=r.get('quality') or {}
        return q.get('reason','') if isinstance(q,dict) else q[1] if isinstance(q,list) and len(q)==4 else ''
    usability=desktop.get('usability') or {}
    desktop_reason=reason(desktop)+' '+(usability.get('reason','') if isinstance(usability,dict) else '')
    return scale_loss(desktop_reason) and device_scale_claim(reason(row))


LAYOUT_IMPACTS={'none','unreadable_subject','missed_action','occluded_interaction','distorted_view','insufficient_framing','specific_craft_defect'}

def layout_context_required(owner,row,scene):
    if not scene or owner not in {'composition','desktop'}:return False
    q=row.get('independent_quality') or row.get('quality') or {}
    if not isinstance(q,dict) or q.get('execution') not in {'weak','basic','competent','considered'}:return False
    if row.get('independent_quality') and not re.search(r'过小|太小|不可辨|遮挡|出画|变形|受阻|冲突|失衡|过多|过大|浪费|低效|不足|松散|拥挤',str(q.get('reason',''))):return False
    return True
