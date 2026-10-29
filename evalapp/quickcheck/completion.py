"""Schema-only completion: only enumerated missing fields may be patched."""
import copy
from .policy import ITEMS, COMPLIANCE, QUALITY_ANCHORS
from .attribution import shared_desktop_loss,layout_context_required,LAYOUT_IMPACTS
from .harness import canonical_rows


def normalize(raw):
    data = {k: copy.deepcopy(raw.get(k)) for k in ('items', 'adjustments', 'compliance')}
    if 'presentation' in raw:data['presentation']=copy.deepcopy(raw['presentation'])
    for key in ('items', 'adjustments', 'compliance'):
        data[key] = canonical_rows(data[key], ('status','reason','evidence_ids') if key=='compliance' else None)
    for item in data['items']:
        if not isinstance(item, dict):
            continue
        for key in ('quality','independent_quality'):
            q = item.get(key)
            if isinstance(q, list) and len(q) == 4:
                item[key] = dict(zip(('execution', 'reason', 'evidence_ids', 'refinements'), q))
        item['checks'] = canonical_rows(item.get('checks'), ('verdict','reason','evidence_ids'))
        if isinstance(item.get('checks'), list):
            item['checks'] = [dict(zip(('id', 'verdict', 'reason', 'evidence_ids'), c))
                              if isinstance(c, list) and len(c) == 4 else c for c in item['checks']]
    return data


def _row(rows, key):
    matches = [r for r in rows if isinstance(r, dict) and r.get('id') == key] if isinstance(rows, list) else []
    return matches[0] if len(matches) == 1 else None


def missing_fields(data, technical):
    catalog = {e['id']: e for e in technical.get('evidence', [])}
    missing = []
    def need(path, expected):
        missing.append({'path': path, 'expected': expected})
    def image_ids(value, owner=None, required=True):
        return (isinstance(value, list) and all(isinstance(e, str) and e in catalog for e in value)
                and (not required or any(catalog[e].get('type') == 'screenshot' and
                     (owner not in ('mobile', 'desktop') or catalog[e].get('device') == owner) for e in value)))
    presentation=data.get('presentation') or {}
    scene=isinstance(presentation,dict) and presentation.get('kind')=='immersive_scene'
    for owner, spec in ITEMS.items():
        row = _row(data.get('items'), owner)
        base = ['items', owner]
        if row is None:
            # Conflicting duplicate rows are ambiguous; never overwrite judgments.
            if not any(isinstance(r, dict) and r.get('id') == owner for r in data.get('items') or []):
                need(base, 'item with matching id, quality and registered checks')
            continue
        active_quality=row.get('independent_quality') or row.get('quality') or {}
        needs_layout=layout_context_required(owner,row,scene)
        if needs_layout:
            impact=row.get('layout_impact')
            if not isinstance(impact,dict):need(base+['layout_impact'],'type one of '+ '|'.join(sorted(LAYOUT_IMPACTS)) +', concrete reason, actual screenshot evidence_ids; preserve existing quality')
            else:
                if not impact.get('type'):need(base+['layout_impact','type'],'one of '+ '|'.join(sorted(LAYOUT_IMPACTS)))
                if not isinstance(impact.get('reason'),str) or not impact['reason'].strip():need(base+['layout_impact','reason'],'concrete layout impact reason')
                if not image_ids(impact.get('evidence_ids'),owner):need(base+['layout_impact','evidence_ids'],'actual screenshot IDs for layout impact')
        if shared_desktop_loss(owner,row,data['items']):
            independent=row.get('independent_quality')
            path=base+['independent_quality']
            if not isinstance(independent,dict):need(path,'four-field quality evaluating ONLY independent craft; desktop-scale fact is owned by desktop; do not change existing quality')
            else:
                if not independent.get('execution'):need(path+['execution'],'independent completion anchor')
                if not isinstance(independent.get('reason'),str) or not independent['reason'].strip():need(path+['reason'],'independent craft reason without shared desktop-scale loss')
                if not image_ids(independent.get('evidence_ids')):need(path+['evidence_ids'],'actual screenshot IDs for independent craft')
                if not isinstance(independent.get('refinements'),list):need(path+['refinements'],'independent refinement facts; [] permitted')
        if owner == 'desktop':
            usability=row.get('usability')
            if not isinstance(usability,dict):need(base+['usability'],'level clear|strained|difficult|blocked, concrete core-task reason, desktop screenshot evidence_ids')
            else:
                if not usability.get('level'):need(base+['usability','level'],'clear|strained|difficult|blocked')
                if not isinstance(usability.get('reason'),str) or not usability['reason'].strip():need(base+['usability','reason'],'concrete core-task usability reason')
                if not image_ids(usability.get('evidence_ids'),'desktop'):need(base+['usability','evidence_ids'],'desktop screenshot evidence_ids')
        if owner == 'creative_expression':
            scope=row.get('creative_scope')
            if not isinstance(scope,dict):
                need(base+['creative_scope'],'tier none|surface_style|distinctive_expression|integrated_expression, reason, actual screenshot evidence_ids; preserve existing quality')
            else:
                if not scope.get('tier'):need(base+['creative_scope','tier'],'creative contribution scope enum')
                if not isinstance(scope.get('domains'),list):need(base+['creative_scope','domains'],'list of actual expression domains style|imagery|spatial|interaction|theme_detail; color, font, CRT are all style; [] for none')
                if not isinstance(scope.get('reason'),str) or not scope['reason'].strip():need(base+['creative_scope','reason'],'concrete contribution scope reason')
                if not image_ids(scope.get('evidence_ids')):need(base+['creative_scope','evidence_ids'],'actual screenshot evidence_ids')
        q = row.get('quality')
        if not isinstance(q, dict):
            need(base + ['quality'], 'quality: execution, reason, evidence_ids, refinements')
        else:
            allowed = set(QUALITY_ANCHORS) | ({'none'} if owner == 'creative_expression' else set())
            # A present judgment is frozen, including an explicit unknown value.
            if not q.get('execution'):
                need(base + ['quality', 'execution'], 'one of ' + '|'.join(sorted(allowed)))
            if not isinstance(q.get('reason'), str) or not q['reason'].strip():
                need(base + ['quality', 'reason'], 'concrete reason for existing judgment')
            if not image_ids(q.get('evidence_ids'), owner):
                need(base + ['quality', 'evidence_ids'], 'actual screenshot IDs supporting existing judgment')
            if not isinstance(q.get('refinements'), list):
                need(base + ['quality', 'refinements'], 'visible refinement facts; [] permitted')
        for cid in spec['checks']:
            check = _row(row.get('checks'), cid)
            path = base + ['checks', cid]
            if check is None:
                if not any(isinstance(r, dict) and r.get('id') == cid for r in row.get('checks') or []):
                    need(path, 'check with matching id, verdict, reason, evidence_ids')
                continue
            if not check.get('verdict'):
                need(path + ['verdict'], 'yes|partial|no|unknown|na')
            if not isinstance(check.get('reason'), str) or not check['reason'].strip():
                need(path + ['reason'], 'concrete reason, preserve existing verdict')
            known = check.get('verdict') in ('yes', 'partial', 'no')
            # A measured technical fact is sufficient for exclusion from subjective scoring.
            ids = check.get('evidence_ids')
            measured = isinstance(ids, list) and all(isinstance(e, str) and e in catalog for e in ids) and any(catalog[e].get('type') == 'measured_issue' for e in ids)
            if not measured and not image_ids(ids, owner, required=known):
                need(path + ['evidence_ids'], 'actual evidence IDs; corresponding device for known verdict')
    for cid in COMPLIANCE:
        row = _row(data.get('compliance'), cid)
        path = ['compliance', cid]
        if row is None:
            if not any(isinstance(r, dict) and r.get('id') == cid for r in data.get('compliance') or []):
                need(path, 'content check with matching id, status, reason, evidence_ids')
            continue
        if not row.get('status'):
            need(path + ['status'], 'clear|violation|unknown')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            need(path + ['reason'], 'reason for existing status')
        if not image_ids(row.get('evidence_ids'), required=row.get('status') in ('clear', 'violation')):
            need(path + ['evidence_ids'], 'actual screenshot IDs supporting existing status')
    return missing


def apply_patches(data, response, requested):
    """Whitelist exact paths. Patching a missing parent cannot replace known siblings."""
    merged = copy.deepcopy(data)
    allowed = {tuple(r['path']) for r in requested}
    applied = []; rejected = []
    patches = response.get('patches', []) if isinstance(response, dict) else []
    for patch in patches if isinstance(patches, list) else []:
        path = patch.get('path') if isinstance(patch, dict) else None
        if not isinstance(path, list) or not all(isinstance(p, str) for p in path) or tuple(path) not in allowed or 'value' not in patch:
            rejected.append(path); continue
        node = merged
        try:
            for token in path[:-1]:
                if isinstance(node, list):
                    node = _row(node, token)
                elif isinstance(node, dict):
                    if node.get(token) is None:
                        node[token] = [] if token in ('items', 'checks', 'compliance') else {}
                    node = node[token]
                else:
                    raise ValueError()
            value = copy.deepcopy(patch['value']); last = path[-1]
            if isinstance(node, list):
                if len(path) >= 4 and path[-2] == 'checks' and isinstance(value, list) and len(value) == 4:
                    value = dict(zip(('id', 'verdict', 'reason', 'evidence_ids'), value))
                if isinstance(value, dict) and 'id' not in value:
                    value['id'] = last
                if _row(node, last) is not None or not isinstance(value, dict) or value.get('id') != last:
                    raise ValueError()
                node.append(value)
            elif isinstance(node, dict):
                node[last] = value
            else:
                raise ValueError()
            applied.append(path); allowed.remove(tuple(path))
        except (ValueError, TypeError, KeyError):
            rejected.append(path)
    return normalize(merged), {'applied_paths': applied, 'rejected_paths': rejected}
