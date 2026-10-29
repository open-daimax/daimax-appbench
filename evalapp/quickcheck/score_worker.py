"""Deterministic hierarchical scoring worker with an auditable point ledger."""
import hashlib
import json
import re
from .attribution import shared_desktop_loss, device_scale_claim,layout_context_required,LAYOUT_IMPACTS
from .policy import ITEMS, GROUPS, BONUS_RULES, DEDUCTION_RULES, BONUS_POINTS, DEDUCTION_POINTS, CHECK_VALUES, COMPLIANCE, QUALITY_ANCHORS, OVERALL_WEIGHTS, RUNTIME_PENALTY_WEIGHT


def _id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def score_assessment(assessment, technical, policy=None):
    """No model calls. Technical facts, subjective facts and arithmetic have distinct owners."""
    from .policy import resolve_scoring
    rules = policy if policy is not None else resolve_scoring()
    items=rules['items']; anchors=rules['quality_anchors']; deductions=rules['deduction_points']; overall_weights=rules['overall_weights']; runtime_weight=rules['runtime_penalty_weight']
    assessment = assessment if isinstance(assessment, dict) else {}
    catalog = {e['id']: e for e in technical.get('evidence', [])}
    entries = []; warnings = []; children = {}; seen = set()
    raw_items = assessment.get('items', [])
    raw_items = raw_items if isinstance(raw_items, list) else []
    by_id = {}
    for row in raw_items:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row.get('id') not in items:
            warnings.append({'code': 'unknown_item'}); continue
        if row['id'] in by_id:
            by_id[row['id']] = None
            warnings.append({'code': 'duplicate_item', 'item': row['id']})
        else:
            by_id[row['id']] = row

    def evidence_ids(row):
        ids = row.get('evidence_ids', [])
        return ids if isinstance(ids, list) and all(isinstance(i, str) and i in catalog for i in ids) else None

    def has_image(ids, owner=None):
        return any(catalog[i].get('type') == 'screenshot' and (owner not in {'mobile', 'desktop'} or catalog[i].get('device') == owner) for i in ids or [])

    def technical_owner(row, ids):
        for eid in ids or []:
            if catalog[eid].get('type') == 'measured_issue':
                return eid
        text = ' '.join(str(row.get(k, '')) for k in ('reason', 'observation', 'affected_text'))
        if re.search(r'裁切|截断|溢出|超出.*视口|clipp|cut.?off|overflow', text, re.I):
            for issue in technical.get('issues', []):
                if any(label and label in text for label in issue.get('affected_texts', [])):
                    return issue['id']
        return None

    def ledger(kind, owner, rule, points, reason, ids=None, decision='applied', **extra):
        row = {'id': 'entry_' + _id([len(entries), kind, owner, rule, reason]), 'kind': kind, 'owner': owner,
               'group': items[owner]['group'] if owner in items else owner.split('.')[0], 'rule_id': rule,
               'points': points, 'reason': reason, 'evidence_ids': ids or [], 'decision': decision, **extra}
        entries.append(row)
        return row

    shared_owners={owner for owner,row in by_id.items() if isinstance(row,dict) and shared_desktop_loss(owner,row,raw_items)} if rules.get('semantic_calibration') else set()
    presentation=assessment.get('presentation') or {}
    scene = isinstance(presentation,dict) and presentation.get('kind')=='immersive_scene' and has_image(evidence_ids(presentation))

    for owner, spec in items.items():
        source = by_id.get(owner)
        checks = source.get('checks', []) if isinstance(source, dict) else []
        checks = checks if isinstance(checks, list) else []
        check_map = {}; duplicates = set()
        for check in checks:
            if isinstance(check, dict) and isinstance(check.get('id'), str) and check.get('id') in spec['checks']:
                if check['id'] in check_map: duplicates.add(check['id'])
                check_map[check['id']] = check
        normalized = []; eligible = []; unknown = False
        for cid, label in spec['checks'].items():
            row = check_map.get(cid, {}); verdict = row.get('verdict', 'unknown'); ids = evidence_ids(row)
            reason = row.get('reason')
            if cid in duplicates or not isinstance(verdict, str) or verdict not in CHECK_VALUES or not isinstance(reason, str) or not reason.strip() or ids is None:
                verdict = 'unknown'; reason = '检查点缺失、重复或输出不符合约定。'; ids = []
            if rules.get('semantic_calibration') and owner=='typography' and verdict in {'partial','no'} and re.search(r'常规|默认|差异不大|层级.*平|靠位置|普通字',str(reason)) and not re.search(r'过小|太小|拥挤|模糊|难读|不清|混淆|低对比|对比不足|不可辨|重叠|错位',str(reason)):
                impact=source.get('typography_impact') or {}
                no_loss=isinstance(impact,dict) and str(impact.get('reading_loss','')).strip().lower() in {'none','无','无阅读障碍','无阅读损失'}
                if no_loss and has_image(ids):
                    normalized.append({'id':cid,'label':label,'verdict':'excluded','reason':'已明确无阅读损失，字形常规或字号层级数量本身不扣分。','evidence_ids':ids})
                    eligible.append(1)
                    ledger('base_check',owner,cid,0,reason,ids,decision='excluded_non_readability_style')
                    continue
            if rules.get('semantic_calibration') and owner=='components' and cid=='visible_states' and verdict=='unknown' and re.search(r'静态|截图|未测试|未点击|未观察|无法判断',str(reason)) and re.search(r'选中|悬停|反馈|交互|点击|hover',str(reason),re.I) and has_image(evidence_ids(source.get('quality') or {})):
                verdict='na';reason='未操作的交互状态不在当前截图评测范围，不阻断已有可见控件计分。'
            if verdict in {'yes', 'partial', 'no'} and not has_image(ids, owner) and not technical_owner(row, ids):
                verdict = 'unknown'; reason = '缺少对应画面的有效证据。'
            if owner in shared_owners and verdict in {'yes','partial','no'} and device_scale_claim(reason):
                normalized.append({'id':cid,'label':label,'verdict':'excluded','reason':'该PC尺度事实仅归桌面适配，本项使用独立完成度依据。','evidence_ids':ids})
                eligible.append(1)
                ledger('base_check',owner,cid,0,reason,ids,decision='excluded_shared_desktop_loss')
                continue
            conflict = technical_owner(row, ids)
            if verdict != 'unknown' and conflict:
                normalized.append({'id': cid, 'label': label, 'verdict': 'excluded', 'reason': '此事实已归技术扣分，未再次影响基础分。', 'evidence_ids': ids})
                ledger('base_check', owner, cid, 0, reason, ids, decision='excluded_technical_owner', technical_fact=conflict)
                continue
            normalized.append({'id': cid, 'label': label, 'verdict': verdict, 'reason': reason, 'evidence_ids': ids})
            if verdict == 'unknown': unknown = True
            if verdict != 'na': eligible.append(CHECK_VALUES.get(verdict))
        primary=source.get('quality') if isinstance(source,dict) else {}
        valid_primary=isinstance(primary,dict) and primary.get('execution') in set(anchors)|{'none'} and has_image(evidence_ids(primary),owner)
        if rules.get('grounded_gap_required') and unknown and (valid_primary or any(r['verdict'] in {'yes','partial','no','excluded'} for r in normalized)):
            unknown=False
        base = None if unknown or not eligible else 0 if owner == 'creative_expression' else 100
        state = 'not_applicable' if not unknown and not eligible else 'unknown' if base is None else 'completed'
        children[owner] = {'id': owner, 'label': spec['label'], 'weight': spec['weight'], 'status': state, 'base_score': base,
                           'bonus': 0, 'deduction': 0, 'score': base, 'checks': normalized, 'reasons': [r['reason'] for r in normalized if r['verdict'] in {'unknown', 'partial', 'no'}], 'ledger_ids': []}
        entry = ledger('base', owner, 'foundation_checkpoints', base, '创意从0分开始，仅按有证据的创作贡献加分。' if owner == 'creative_expression' else '证据完整时从100分起评；质量检查点及具体缺陷按归属去重扣分。', decision='applied' if base is not None else 'unknown')
        children[owner]['ledger_ids'].append(entry['id'])

    adjustments = assessment.get('adjustments', [])
    adjustments = adjustments if isinstance(adjustments, list) else []
    # Canonical order prevents arrival order from deciding a duplicate's owner.
    adjustments = sorted([r for r in adjustments if isinstance(r, dict)], key=lambda r: (str(r.get('fact_id', '')), str(r.get('rule_id', ''))))
    for row in adjustments:
        kind = row.get('kind'); rule = row.get('rule_id'); levels = BONUS_POINTS if kind == 'bonus' else deductions
        registry = BONUS_RULES if kind == 'bonus' else DEDUCTION_RULES
        if not isinstance(kind, str) or kind not in {'bonus', 'deduction'} or not isinstance(rule, str) or rule not in registry or not isinstance(row.get('level'), str) or row.get('level') not in levels:
            warnings.append({'code': 'invalid_adjustment_rule', 'rule': rule}); continue
        owner = registry[rule][0]; ids = evidence_ids(row); observation = row.get('observation'); fact = row.get('fact_id')
        if ids is None or not has_image(ids, owner) or not isinstance(observation, str) or not observation.strip() or not isinstance(fact, str) or not fact.strip():
            warnings.append({'code': 'invalid_adjustment_evidence', 'rule': rule}); continue
        if kind=='deduction' and owner in shared_owners and device_scale_claim(observation):
            ledger(kind,owner,rule,0,observation,ids,decision='excluded_shared_desktop_loss',fact_id=fact)
            continue
        if scene and kind=='deduction' and rule in {'desktop_space_waste','wasted_composition','hierarchy_conflict'}:
            impacts={'unreadable_subject','missed_action','occluded_interaction','distorted_view','insufficient_framing'}
            if row.get('task_impact') not in impacts or not isinstance(row.get('impact_reason'),str) or not row['impact_reason'].strip():
                entry=ledger(kind,owner,rule,0,'沉浸场景的环境与负空间不能仅按页面留白扣分；未提供具体任务损失。',ids,decision='excluded_scene_context',fact_id=fact)
                children[owner]['ledger_ids'].append(entry['id'])
                warnings.append({'code':'unsupported_scene_layout_deduction','rule':rule})
                continue
        if kind=='deduction' and owner=='typography' and not (isinstance(row.get('location'),str) and row['location'].strip() and isinstance(row.get('reading_loss'),str) and row['reading_loss'].strip()):
            entry=ledger(kind,owner,rule,0,'字体扣分缺少具体位置与阅读损失，常规字体本身不扣分。',ids,decision='excluded_typography_evidence',fact_id=fact)
            children[owner]['ledger_ids'].append(entry['id'])
            warnings.append({'code':'unsupported_typography_deduction','rule':rule})
            continue
        if rule == 'emoji_asset_substitution' and not re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]',''.join(str(row.get('affected_text', '')))):
            ledger(kind, owner, rule, 0, '未提供实际Emoji字符，不能仅凭图标风格推断，已排除此扣分。', ids, decision='excluded_unconfirmed_emoji', fact_id=fact)
            continue
        if kind == 'bonus' and (not isinstance(row.get('benefit'), str) or not row['benefit'].strip()):
            warnings.append({'code': 'missing_bonus_benefit', 'rule': rule}); continue
        conflict = technical_owner(row, ids)
        if kind == 'deduction' and conflict:
            ledger(kind, owner, rule, 0, observation, ids, decision='excluded_technical_owner', technical_fact=conflict); continue
        # Same asset may have different attributes. Same declared fact or repeated rule is counted once.
        family = 'stock_icon_assets' if rule in {'emoji_asset_substitution', 'generic_icon_system'} else rule
        duplicate = (kind, fact) in seen or (kind, owner, family) in seen
        if duplicate:
            ledger(kind, owner, rule, 0, observation, ids, decision='excluded_duplicate', fact_id=fact); continue
        seen.add((kind, fact)); seen.add((kind, owner, family))
        child = children[owner]
        if child['base_score'] is None:
            ledger(kind, owner, rule, 0, observation, ids, decision='unscored_unknown_base', fact_id=fact); continue
        cap = 95 if kind == 'bonus' else 100
        amount = 0 if kind == 'bonus' else min(levels[row['level']], max(0, cap - child[kind]))
        child[kind] += amount
        entry = ledger(kind, owner, rule, amount, observation, ids, fact_id=fact, benefit=row.get('benefit'), source='model', decision='supporting_creative_evidence' if kind == 'bonus' else 'applied')
        child['ledger_ids'].append(entry['id'])

    creative = children['creative_expression']
    if creative['base_score'] is not None:
        quality = (by_id.get('creative_expression') or {}).get('quality')
        quality = quality if isinstance(quality, dict) else {}
        support = [e for e in entries if e['owner'] == 'creative_expression' and e['decision'] == 'supporting_creative_evidence']
        execution = quality.get('execution'); ids = evidence_ids(quality); reason = quality.get('reason')
        refinements=quality.get('refinements',[])
        scope=(by_id.get('creative_expression') or {}).get('creative_scope')
        scope_support=isinstance(scope,dict) and scope.get('tier') in {'surface_style','distinctive_expression','integrated_expression'} and isinstance(scope.get('reason'),str) and bool(scope['reason'].strip()) and has_image(evidence_ids(scope))
        direct_facts=(isinstance(refinements,list) and any(isinstance(v,str) and v.strip() for v in refinements)) or scope_support
        if execution == 'none' or (not support and not direct_facts):
            value = 0; execution = 'none'; reason = reason or '没有有效的独特创意贡献证据。'
        elif execution in anchors and has_image(ids) and isinstance(reason, str) and reason.strip():
            value = anchors[execution]
        else:
            value = None; creative.update(status='unknown', base_score=None, score=None)
            warnings.append({'code':'missing_creative_holistic_anchor'})
            reason = '缺少创意整体完成度评级，不能将贡献点直接相加。'
        scope=(by_id.get('creative_expression') or {}).get('creative_scope')
        if rules.get('creative_scope_required') and value is not None:
            caps=rules['creative_scope_caps']
            valid_domains={'style','imagery','spatial','interaction','theme_detail'}
            domains=scope.get('domains') if isinstance(scope,dict) else None
            valid=isinstance(scope,dict) and scope.get('tier') in caps and isinstance(domains,list) and all(isinstance(d,str) and d in valid_domains for d in domains) and (scope.get('tier')=='none' or bool(domains)) and isinstance(scope.get('reason'),str) and scope['reason'].strip() and has_image(evidence_ids(scope))
            if not valid and rules.get('grounded_gap_required'):
                value=min(value,anchors[caps['surface_style']])
                creative['scoring_source']='conservative_creative_scope_cap'
                reason='贡献范围元数据缺漏，按已有创意判断与局部表达上限计分。'
            elif not valid:
                value=None;creative.update(status='unknown',base_score=None,score=None)
                warnings.append({'code':'missing_creative_scope'})
                reason='缺少有效的创意贡献范围证据，不能确认高分。'
            else:
                tier=scope['tier']
                if tier!='none' and (set(domains)<= {'style','theme_detail'} or (tier=='distinctive_expression' and len(set(domains))<2)):
                    tier='surface_style'
                    warnings.append({'code':'single_expression_domain_scope_cap'})
                cap_band=caps[tier];cap=0 if cap_band=='none' else anchors[cap_band]
                creative['creative_scope']={**scope,'effective_tier':tier}
                if value>cap:
                    value=cap;execution=cap_band
                    reason=scope['reason']+'；按贡献范围上限评级。'
        creative.update(bonus=value or 0, quality_execution=execution, quality_anchor_score=value, quality_reason=reason)
        creative['reasons'].append(reason)
        entry = ledger('bonus','creative_expression','creative_holistic_quality',value,reason,ids,source='holistic_quality',decision='applied' if value is not None else 'unknown',execution=execution,supporting_entry_ids=[e['id'] for e in support])
        creative['ledger_ids'].append(entry['id'])

    # Quality checkpoints are an actionable fallback, never a second penalty
    # on top of registered defects within the same scoring item.
    for owner, child in children.items():
        if owner == 'creative_expression' or child['base_score'] is None:
            continue
        covered = any(e['owner'] == owner and e['kind'] == 'deduction' and e['decision'] == 'applied' for e in entries)
        for check in child['checks']:
            if check['verdict'] not in {'partial', 'no'}:
                continue
            amount = rules['checkpoint_deductions'][check['verdict']]
            entry = ledger('deduction', owner, 'quality_checkpoint_' + check['id'], 0 if covered else amount,
                           check['reason'], check['evidence_ids'],
                           decision='excluded_registered_owner' if covered else 'applied', source='checkpoint')
            child['ledger_ids'].append(entry['id'])
            if not covered:
                child['deduction'] += amount

    # Calibrate subjective completion beyond presence/absence. The quality
    # gap only fills the residual beyond defects already charged to this item.
    for owner, child in children.items():
        if owner == 'creative_expression' or child['base_score'] is None:
            continue
        source = by_id.get(owner) or {}
        quality = source.get('independent_quality') if owner in shared_owners else source.get('quality')
        quality = quality if isinstance(quality, dict) else {}
        if owner in shared_owners and device_scale_claim(quality.get('reason','')):
            quality={}
        execution = quality.get('execution')
        ids = evidence_ids(quality)
        reason = quality.get('reason')
        fallback_quality=False
        if rules.get('grounded_gap_required') and (execution not in anchors or not isinstance(reason,str) or not reason.strip() or not has_image(ids,owner)):
            fallback_quality=True;execution='competent' if rules.get('completion_rating_mode') else 'exceptional'
            ids=list(dict.fromkeys(e for c in child['checks'] for e in c['evidence_ids']))
            reason='辅助评级不可用，按已有画面检查点与明确缺陷计分。'
            quality={'refinements':[]}
            child['scoring_source']='checkpoint_fallback'
            warnings.append({'code':'checkpoint_scoring_fallback','item':owner})
        if not rules.get('grounded_gap_required') and (execution not in anchors or not isinstance(reason, str) or not reason.strip() or not has_image(ids, owner)):
            child.update(status='unknown', base_score=None, score=None)
            child['reasons'].append('缺少有效的主观完成度档位或证据，不能默认满分。')
            warnings.append({'code': 'missing_quality_anchor', 'item': owner})
            continue
        # Ordinary letterforms are not a loss when every observed readability check passes.
        # Preserve unknown when evidence or an actual adverse check is missing.
        ordinary_only=(owner=='typography' and execution in {'weak','basic','competent','considered'} and re.search(r'常规|默认|普通字|通用字|(?:ordinary|default|generic).*font|font.*(?:ordinary|default|generic)',reason,re.I))
        impact=source.get('typography_impact') or {}
        valid_reading_loss=isinstance(impact,dict) and isinstance(impact.get('location'),str) and bool(impact['location'].strip()) and isinstance(impact.get('reading_loss'),str) and bool(impact['reading_loss'].strip()) and has_image(evidence_ids(impact))
        if rules.get('semantic_calibration') and ordinary_only and not valid_reading_loss and child['checks'] and all(c['verdict'] in {'yes','excluded'} for c in child['checks']) and any(c['verdict']=='yes' for c in child['checks']) and child['deduction']==0 and not re.search(r'过小|太小|拥挤|模糊|难读|不清|低对比|对比不足|不可辨|截断|重叠|错位|too small|illegible|unreadable',reason,re.I):
            execution='refined';reason='可读性、层级和任务匹配检查均通过；常规字形本身不构成缺陷。'
            quality={**quality,'refinements':[c['reason'] for c in child['checks']]}
            warnings.append({'code':'ordinary_font_not_a_defect','item':owner})
        refinements = quality.get('refinements', [])
        refinements = [v for v in refinements if isinstance(v, str) and v.strip()] if isinstance(refinements, list) else []
        required = 2 if execution == 'exceptional' else 1 if execution == 'refined' else 0
        if not fallback_quality and len(set(refinements)) < required:
            warnings.append({'code': 'unsupported_high_quality_anchor', 'item': owner})
            execution = 'competent'
            reason = '缺少高完成度的具体打磨证据；' + reason
        suppress_gap=False
        if layout_context_required(owner,{**source,'quality':{**quality,'execution':execution}},scene):
            impact=source.get('layout_impact') or {}
            allowed=LAYOUT_IMPACTS-{'none'}
            unsupported_space_claim=bool(re.search(r'(?:UI|HUD|界面).*?(?:稀疏|空旷|sparse)|(?:空白|留白|背景).*(?:过大|略大|过多|浪费|利用不足)',reason,re.I))
            valid_impact=isinstance(impact,dict) and impact.get('type') in (allowed|{'none'}) and isinstance(impact.get('reason'),str) and bool(impact['reason'].strip()) and has_image(evidence_ids(impact),owner)
            if not valid_impact or (impact.get('type')=='none' and unsupported_space_claim):
                if rules.get('grounded_gap_required'):
                    suppress_gap=True
                    warnings.append({'code':'excluded_unsupported_scene_gap','item':owner})
                else:
                    child.update(status='unknown',base_score=None,score=None)
                child['reasons'].append('沉浸场景降档缺少具体取景、操作或制作损失证据，不能仅因稀疏或留白降档。')
                warnings.append({'code':'unsupported_scene_quality_gap','item':owner})
                if not rules.get('grounded_gap_required'):continue
        if owner=='typography' and execution in {'weak','basic','competent','considered'} and re.search(r'常规|默认|普通字|通用字|(?:ordinary|default|generic).*font|font.*(?:ordinary|default|generic)',reason,re.I):
            impact=source.get('typography_impact') or {}
            if not isinstance(impact,dict) or not isinstance(impact.get('location'),str) or not impact['location'].strip() or not isinstance(impact.get('reading_loss'),str) or not impact['reading_loss'].strip() or not has_image(evidence_ids(impact)):
                if rules.get('grounded_gap_required'):suppress_gap=True
                else:child.update(status='unknown',base_score=None,score=None)
                child['reasons'].append('不能仅以字体常规或默认降档，需具体阅读损失证据。')
                warnings.append({'code':'unsupported_typography_quality_gap','item':owner})
                if not rules.get('grounded_gap_required'):continue
        if owner=='desktop' and rules.get('semantic_calibration'):
            usability=source.get('usability') or {}
            caps=rules['desktop_usability_caps']
            if not isinstance(usability,dict) or usability.get('level') not in caps or not isinstance(usability.get('reason'),str) or not usability['reason'].strip() or not has_image(evidence_ids(usability),'desktop'):
                if not rules.get('grounded_gap_required'):child.update(status='unknown',base_score=None,score=None)
                child['reasons'].append('缺少原始桌面截图的核心任务可用性证据。')
                warnings.append({'code':'missing_desktop_usability'})
                if not rules.get('grounded_gap_required'):continue
            child['usability']=usability
            cap_band=caps.get(usability.get('level'),'exceptional')
            if anchors[execution]>anchors[cap_band]:
                execution=cap_band;reason=usability['reason']+'；按核心操作可用性上限评级。'
                child['adaptation_limit']={'cap':anchors[cap_band],'reason':reason}
        if owner in {'mobile','desktop'} and rules.get('device_layout_cap'):
            checks={c['id']:c['verdict'] for c in child['checks']}
            structure=checks.get('structure');framing=checks.get('framing')
            layout_failed=structure in {'partial','no'} and (structure=='no' or framing in {'partial','no'} or anchors[execution]<=anchors['competent'])
            cap_band=rules['device_layout_cap']
            if layout_failed and anchors[execution]>anchors[cap_band]:
                limit_reason='设备核心布局未达到要求；可显示或可辨认不等于适配合格。'
                child['adaptation_limit']={'cap':anchors[cap_band],'reason':limit_reason}
                execution=cap_band;reason=reason+'；'+limit_reason
        target = anchors[execution]
        if rules.get('completion_rating_mode'):
            child.update(quality_execution=execution,quality_anchor_score=target,quality_reason=reason,
                         rating_score=target,rating_reason=reason)
            child['reasons'].append(reason)
            noted_gap=source.get('completion_gap') or {}
            if isinstance(noted_gap,dict) and noted_gap.get('status')=='observed' and all(isinstance(noted_gap.get(k),str) and noted_gap[k].strip() for k in ('location','reason')) and has_image(evidence_ids(noted_gap),owner):
                child['completion_gap']=noted_gap
            entry=ledger('rating',owner,'completion_rating',0,reason,ids,source='completion_rating',anchor_score=target,
                         decision='checkpoint_fallback' if fallback_quality else 'evidenced_rating',refinements=refinements)
            child['ledger_ids'].append(entry['id'])
            continue
        gap = 100 - target
        gap_reason=reason
        if rules.get('grounded_gap_required'):
            loss=source.get('completion_gap') or {}
            grounded=isinstance(loss,dict) and loss.get('status')=='observed' and all(isinstance(loss.get(k),str) and loss[k].strip() for k in ('reason','location')) and has_image(evidence_ids(loss),owner)
            if child.get('adaptation_limit'):
                gap_reason=child['adaptation_limit']['reason']
            elif grounded and not suppress_gap and not fallback_quality:
                gap_reason=loss['location']+'：'+loss['reason'];ids=evidence_ids(loss)
            elif not suppress_gap and not fallback_quality and any(e['owner']==owner and e['kind']=='deduction' and e['points']>0 and e.get('source') in {'model','checkpoint'} for e in entries):
                supporting=[e for e in entries if e['owner']==owner and e['kind']=='deduction' and e['points']>0 and e.get('source') in {'model','checkpoint'}]
                gap_reason='；'.join(e['reason'] for e in supporting)
                ids=list(dict.fromkeys(eid for e in supporting for eid in e['evidence_ids']))
            else:
                gap=0;gap_reason='未提供具体不足，不按建议档位额外扣分。'
                child['scoring_source']=child.get('scoring_source','observed_checks_and_defects')
        amount = max(0, gap - child['deduction'])
        child['deduction'] += amount
        child['quality_execution'] = execution if gap else None
        child['quality_anchor_score'] = target if gap else None
        child['quality_reason'] = reason
        child['reasons'].append(reason)
        entry = ledger('deduction', owner, 'subjective_completion_gap', amount, gap_reason, ids,
                       source='quality_anchor', execution=execution, anchor_score=target, rating_basis=reason,
                       refinements=refinements, decision='applied' if amount else 'covered_by_existing_defects' if gap else 'exceptional_evidenced')
        child['ledger_ids'].append(entry['id'])

    for issue in technical.get('issues', []):
        owner = issue.get('owner')
        if owner not in children: continue
        child = children[owner]
        geometry = rules['geometry_deductions']
        measured = issue.get('evidence', {})
        points = geometry['clipped_control' if measured.get('clipped_controls') else 'overflow_only'] if issue.get('rule_id') == 'viewport_geometry' else issue['deduction']
        amount = points if child['base_score'] is not None else 0
        child['deduction'] += amount
        child['technical_deduction']=child.get('technical_deduction',0)+amount
        entry = ledger('deduction', owner, issue['rule_id'], amount, '采集到的视口几何问题，仅在对应设备计罚。', [issue['id']], source='collector', fact_id=issue['id'], decision='applied' if amount else 'unscored_unknown_base')
        child['ledger_ids'].append(entry['id'])
        child['reasons'].append(entry['reason'])
    for child in children.values():
        if child['base_score'] is not None:
            if rules.get('grounded_gap_required') and child['id']!='creative_expression':
                child['score_ceiling']=95
                child['score_ceiling_applied']=child['base_score']+child['bonus']-child['deduction']>95
            child['score'] = round(max(0, min(95 if rules.get('grounded_gap_required') else 100, child['base_score'] + child['bonus'] - child['deduction'])), 2)
    if rules.get('completion_rating_mode'):
        for child in children.values():
            if child['base_score'] is not None and child['id']!='creative_expression':
                technical_loss=child.get('technical_deduction',0)
                observed_loss=child['deduction']-technical_loss
                rating=child.get('rating_score',anchors['competent'])
                child['score']=round(max(0,min(rating,100-observed_loss)-technical_loss),2)
                child['score_ceiling_applied']=False
                child['scoring_formula']='completion_rating_and_observed_defects'
    groups = {}
    for key in ('visual', 'information', 'adaptation'):
        group_items = [children[k] for k, s in items.items() if s['group'] == key]
        relevant = [r for r in group_items if r['status'] != 'not_applicable']
        known = relevant and all(r['score'] is not None for r in relevant)
        value = round(sum(r['score'] * r['weight'] for r in relevant) / sum(r['weight'] for r in relevant), 2) if known else None
        groups[key] = {'label': GROUPS[key][0], 'score': value, 'status': 'completed' if value is not None else 'not_applicable' if not relevant else 'partial', 'items': group_items, 'reasons': [reason for r in group_items for reason in r['reasons']]}
    adaptation=groups['adaptation']
    cap_band=rules.get('adaptation_failed_device_cap')
    if cap_band and adaptation['score'] is not None:
        failed=[r for r in adaptation['items'] if r['score'] is not None and r['score']<anchors['competent']]
        cap=anchors[cap_band]
        if failed and adaptation['score']>cap:
            weighted=adaptation['score']
            reason='、'.join(r['label']+' '+str(r['score'])+'分' for r in failed)+'低于及格线，适配大项按较弱端限制上限。'
            adaptation['aggregation']={'method':'weighted_mean_with_failed_device_cap','weighted_score':weighted,'cap':cap,'limiting_devices':[r['id'] for r in failed],'reason':reason}
            adaptation['score']=cap
            adaptation['reasons'].append(reason)
            ledger('aggregation_cap','adaptation.aggregate','failed_device_cap',round(weighted-cap,2),reason,source='aggregation',cap=cap,weighted_score=weighted)
    groups['operation'] = _operation(technical, ledger, rules['runtime_deductions'])
    groups['compliance'] = _compliance(assessment, catalog, ledger)
    quality_base = round(sum(groups[key]['score'] * weight for key, weight in overall_weights.items()), 2) if all(groups[key]['score'] is not None for key in overall_weights) else None
    confirmed_open_failure = any(device.get('open_failed') is True for device in technical.get('devices', {}).values())
    redline = groups['compliance']['score'] == 0 or confirmed_open_failure or any(r['id'] == 'opening' and r['score'] == 0 for r in groups['operation']['items'])
    runtime_score = groups['operation']['score']
    runtime_penalty = round((100 - runtime_score) * runtime_weight, 2) if runtime_score is not None else None
    overall = 0 if redline else round(max(0, quality_base-runtime_penalty), 2) if quality_base is not None and runtime_penalty is not None and groups['compliance']['score'] is not None else None
    breakdown = {'quality_base':quality_base,'runtime_penalty':runtime_penalty,'runtime_penalty_weight':runtime_weight,'redline_triggered':redline}
    return {'groups': groups, 'score': overall, 'overall_score': overall, 'overall_weights': overall_weights, 'overall_breakdown': breakdown,
            'overall_reason': f'总分=按配置权重计算的质量基分−运行损失×{runtime_weight:.0%}；确认内容红线或无法打开直接0。',
            'gates': {'availability_failed': any(r['id'] == 'opening' and r['score'] == 0 for r in groups['operation']['items']),
                      'visible_content_violation': groups['compliance']['score'] == 0},
            'ledger': {'version': '5.0', 'entries': entries, 'warnings': warnings}}


def _operation(technical, ledger, penalties):
    devices = technical.get('devices', {})
    rows = []
    def add(key, label, known, failures):
        total = sum(r['points'] for r in failures)
        value = max(0, 100 - total) if known else None
        ids = []
        entry = ledger('base', 'operation.' + key, 'observed_baseline', 100 if known else None, '仅代表采集窗口内已记录的观察。', decision='applied' if known else 'unknown', source='collector')
        ids.append(entry['id'])
        for f in failures:
            entry = ledger('deduction', 'operation.' + key, f['rule'], f['points'], f['reason'], source='collector', fact_id=f['fact_id'], details=f.get('details'))
            ids.append(entry['id'])
        rows.append({'id': key, 'label': label, 'status': 'completed' if known else 'unknown', 'base_score': 100 if known else None, 'bonus': 0,
                     'deduction': total if known else 0, 'score': value, 'ledger_ids': ids, 'reasons': [f['reason'] for f in failures]})
    captured = all(devices.get(d, {}).get('captured') for d in ('mobile', 'desktop'))
    opened_known = captured and all(isinstance(devices[d].get('open_failed'), bool) for d in devices)
    open_fail = any(d.get('open_failed') is True for d in devices.values())
    add('opening', '页面打开', opened_known or open_fail, [{'points': penalties['open_failed'], 'rule': 'open_failed', 'fact_id': 'opening', 'reason': '至少一个配置端未能打开页面。'}] if open_fail else [])
    readiness = [d.get('readiness', {}) for d in devices.values() if d.get('captured')]
    blank = any(r.get('state') == 'confirmed_blank_screen' for r in readiness)
    loading = any(r.get('state') == 'persistent_loading' for r in readiness)
    ready_known = captured and len(readiness) == 2 and all(r.get('scorable') is True or r.get('state') in {'confirmed_blank_screen', 'persistent_loading'} for r in readiness)
    add('loading', '首屏加载', ready_known, [{'points': penalties['blank'] if blank else penalties['persistent_loading'], 'rule': 'confirmed_blank_screen' if blank else 'persistent_loading', 'fact_id': 'loading', 'reason': '确认白屏。' if blank else '持续加载未完成。'}] if blank or loading else [])
    error_known = captured and all(isinstance(d.get('errors'), list) for d in devices.values())
    error_roots = {str(message) for d in devices.values() for message in (d.get('errors') or [])}
    add('script_errors', '脚本异常', error_known, [{'points': penalties['script_exception'], 'rule': 'uncaught_exception', 'fact_id': 'js:' + _id(message), 'reason': '观察到未捕获脚本异常。', 'details': message} for message in sorted(error_roots)])
    network_known = captured and all(isinstance(d.get('resource_failures'), list) for d in devices.values())
    failures = {}
    for device, d in devices.items():
        for index, failure in enumerate(d.get('resource_failures') or []):
            root = failure.get('request_id') or f'{device}:{index}'
            critical = failure.get('type') in {'script', 'stylesheet'} and failure.get('same_origin')
            if root not in failures or critical:
                failures[root] = {'critical': critical, 'details': failure}
    for critical, key, label in [(False, 'network_errors', '一般网络请求'), (True, 'critical_resources', '关键脚本与样式资源')]:
        facts = [{'points': penalties['critical_resource_failure'] if critical else penalties['general_request_failure'], 'rule': key, 'fact_id': 'request:' + root, 'reason': '关键资源请求失败。' if critical else '观察到请求失败。', 'details': f['details']} for root, f in sorted(failures.items()) if bool(f['critical']) == critical]
        add(key, label, network_known, facts)
    known = all(r['score'] is not None for r in rows)
    return {'label': GROUPS['operation'][0], 'score': round(sum(r['score'] for r in rows) / len(rows), 2) if known else None,
            'status': 'completed' if known else 'partial', 'items': rows, 'reasons': [s for r in rows for s in r['reasons']],
            'scope': '仅采集观察窗口；没有记录不等于正常。关键资源失败不在一般网络项再次扣分。'}


def _compliance(assessment, catalog, ledger):
    raw = assessment.get('compliance', [])
    raw = raw if isinstance(raw, list) else []
    rows = []; reasons = []
    for key, label in COMPLIANCE.items():
        matching = [r for r in raw if isinstance(r, dict) and r.get('id') == key]
        r = matching[0] if len(matching) == 1 else {}
        ids = r.get('evidence_ids', [])
        valid = isinstance(ids, list) and bool(ids) and all(isinstance(i, str) and i in catalog for i in ids) and any(catalog[i].get('type') == 'screenshot' for i in ids)
        state = r.get('status') if valid and isinstance(r.get('reason'), str) and r['reason'].strip() else 'unknown'
        value = 100 if state == 'clear' else 0 if state == 'violation' else None
        reason = r.get('reason') or '未取得该项有效的可见内容判断。'
        entry = ledger('check', 'compliance.' + key, key, value, reason, ids if valid else [], decision='unknown' if value is None else 'applied', source='model')
        rows.append({'id': key, 'label': label, 'score': value, 'status': 'completed' if value is not None else 'unknown', 'reason': reason, 'base_score': value, 'bonus': 0, 'deduction': 0, 'ledger_ids': [entry['id']], 'evidence_ids': ids if valid else []})
        if value != 100: reasons.append(reason)
    values = [r['score'] for r in rows]
    score = 0 if 0 in values else None if None in values else 100
    return {'label': GROUPS['compliance'][0], 'score': score, 'status': 'completed' if all(v is not None for v in values) else 'partial',
            'items': rows, 'reasons': reasons, 'scope': '仅可见首屏规则，不代表全站法律合规。'}
