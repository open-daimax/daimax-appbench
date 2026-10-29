"""Regression checks for deduction-only quality and creative contribution scoring."""
from copy import deepcopy
from evalapp.quickcheck.policy import ITEMS, BONUS_RULES
from evalapp.quickcheck.score_worker import score_assessment


def fixture():
    technical = {'evidence': [{'id': 'mobile-shot', 'type': 'screenshot', 'device': 'mobile'},
                              {'id': 'desktop-shot', 'type': 'screenshot', 'device': 'desktop'}]}
    assessment = {'items': [{'id': key, 'quality': {'execution': 'exceptional', 'reason': 'Specific detailed craft is evidenced.', 'refinements': ['Precise task hierarchy', 'Refined control rhythm'], 'evidence_ids': ['desktop-shot' if key == 'desktop' else 'mobile-shot']}, 'checks': [
        {'id': cid, 'verdict': 'yes', 'reason': 'Visible structure is complete.',
         'evidence_ids': ['desktop-shot' if key == 'desktop' else 'mobile-shot']}
        for cid in spec['checks']]} for key, spec in ITEMS.items()], 'adjustments': []}
    for row in assessment['items']:
        if row['id']!='creative_expression':row['completion_gap']={'status':'observed','reason':'Specific remaining craft issue.','location':'Main task region','evidence_ids':['desktop-shot' if row['id']=='desktop' else 'mobile-shot']}
    creative=next(r for r in assessment['items'] if r['id']=='creative_expression')
    next(i for i in assessment['items'] if i['id']=='desktop')['usability']={'level':'clear','reason':'Core controls readable.','evidence_ids':['desktop-shot']}
    creative['quality'].update(execution='none',refinements=[])
    creative['creative_scope']={'tier':'integrated_expression','domains':['spatial','interaction'],'reason':'Distinctive scene and task integration.','evidence_ids':['mobile-shot']}
    return assessment, technical


def item(result, owner):
    return next(i for g in result['groups'].values() for i in g['items'] if i['id'] == owner)


def adjustment(kind, rule, fact, level='D2', evidence='mobile-shot'):
    return {'kind': kind, 'rule_id': rule, 'fact_id': fact, 'level': level,
            'affected_text': '📒' if rule == 'emoji_asset_substitution' else '',
            'observation': 'Specific visible evidence.', 'benefit': 'Distinct expressive benefit.',
            'evidence_ids': [evidence]}


def test_only_creativity_has_contribution_rules_and_zero_foundation():
    a, t = fixture()
    r = score_assessment(a, t)
    assert all(owner == 'creative_expression' for owner, _ in BONUS_RULES.values())
    for owner in ITEMS:
        assert item(r, owner)['score'] == (0 if owner == 'creative_expression' else 95)


def test_registered_deductions_and_creative_bonus_are_separate():
    a, t = fixture()
    next(r for r in a['items'] if r['id']=='creative_expression')['quality'].update(execution='exceptional',refinements=['Specific spatial composition','Specific material lighting'])
    a['adjustments'] = [adjustment('deduction', 'emoji_asset_substitution', 'emoji'),
                        adjustment('deduction', 'desktop_space_waste', 'waste', 'D3', 'desktop-shot'),
                        adjustment('bonus', 'scene_craft', 'light', 'B3')]
    r = score_assessment(a, t)
    assert item(r, 'materials')['score'] == 92
    assert item(r, 'desktop')['score'] == 80
    assert item(r, 'creative_expression')['score'] == 95


def test_repeated_fact_and_unknown_evidence_do_not_produce_extra_points():
    a, t = fixture()
    event = adjustment('deduction', 'emoji_asset_substitution', 'emoji')
    a['adjustments'] = [event, deepcopy(event)]
    a['items'][0]['checks'][0]['evidence_ids'] = []
    r = score_assessment(a, t)
    assert item(r, 'materials')['score'] == 92
    assert item(r, 'composition')['score'] is None


def test_old_noncreative_bonus_is_rejected():
    a, t = fixture()
    a['adjustments'] = [adjustment('bonus', 'material_craft', 'old', 'B3')]
    r = score_assessment(a, t)
    assert item(r, 'materials')['score'] == 95
    assert any(w['code'] == 'invalid_adjustment_rule' for w in r['ledger']['warnings'])


def test_creative_rating_never_claims_perfection():
    a, t = fixture()
    next(r for r in a['items'] if r['id']=='creative_expression')['quality'].update(execution='exceptional',refinements=['Specific spatial composition','Specific material lighting'])
    a['adjustments'] = [adjustment('bonus', rule, rule, 'B3') for rule in BONUS_RULES]
    r = score_assessment(a, t)
    assert item(r, 'creative_expression')['bonus'] == 95
    assert item(r, 'creative_expression')['score'] == 95


def test_icon_style_without_actual_emoji_is_not_a_deduction():
    a, t = fixture()
    event = adjustment('deduction', 'emoji_asset_substitution', 'icon')
    event['affected_text'] = ''
    a['adjustments'] = [event]
    r = score_assessment(a, t)
    assert item(r, 'materials')['score'] == 95
    assert any(e['decision'] == 'excluded_unconfirmed_emoji' for e in r['ledger']['entries'])


def test_stock_icon_family_cannot_double_penalize_same_system():
    a, t = fixture()
    a['adjustments'] = [adjustment('deduction', 'emoji_asset_substitution', 'emoji'),
                        adjustment('deduction', 'generic_icon_system', 'stock')]
    r = score_assessment(a, t)
    assert item(r, 'materials')['score'] == 92


def test_failed_quality_checkpoints_are_deducted_without_adjustments():
    a, t = fixture()
    a['items'][0]['checks'][0]['verdict'] = 'partial'
    a['items'][0]['checks'][1]['verdict'] = 'no'
    assert item(score_assessment(a, t), 'composition')['score'] == 72


def test_registered_defect_suppresses_checkpoint_double_penalty():
    a, t = fixture()
    a['items'][0]['checks'][0]['verdict'] = 'partial'
    a['adjustments'] = [adjustment('deduction', 'hierarchy_conflict', 'same-layout')]
    assert item(score_assessment(a, t), 'composition')['score'] == 92


def test_ordinary_information_does_not_get_full_marks():
    a, t = fixture()
    for row in a['items']:
        if row['id'] in ('purpose', 'organization', 'guidance'):
            row['quality'] = {'execution': 'competent', 'reason': 'Clear but ordinary; reduce search cost.', 'evidence_ids': ['mobile-shot'], 'refinements': []}
    r = score_assessment(a, t)
    assert r['groups']['information']['score'] == 60


def test_quality_gap_does_not_stack_with_the_same_item_defect():
    a, t = fixture()
    a['items'][0]['quality'].update(execution='competent', refinements=[])
    a['adjustments'] = [adjustment('deduction', 'hierarchy_conflict', 'layout')]
    assert item(score_assessment(a, t), 'composition')['score'] == 60


def test_missing_anchor_cannot_silently_become_one_hundred():
    a, t = fixture()
    del a['items'][0]['quality']
    assert item(score_assessment(a, t), 'composition')['score'] is None


def test_creativity_is_holistic_not_contribution_count():
    a, t = fixture()
    creative = next(row for row in a['items'] if row['id'] == 'creative_expression')
    creative['quality'].update(execution='refined', reason='Integrated spatial composition and lighting.', refinements=['Specific spatial composition','Specific material lighting'])
    a['adjustments'] = [adjustment('bonus', 'scene_craft', 'light', 'B1')]
    one = item(score_assessment(a, t), 'creative_expression')['score']
    a['adjustments'].append(adjustment('bonus', 'scene_composition', 'space', 'B3'))
    assert one == item(score_assessment(a, t), 'creative_expression')['score'] == 85


def test_calculator_without_distinctive_creative_expression_stays_zero():
    a, t = fixture()
    creative = next(row for row in a['items'] if row['id'] == 'creative_expression')
    creative['quality'].update(execution='none', reason='Conventional calculator interface.')
    assert item(score_assessment(a, t), 'creative_expression')['score'] == 0


def test_overall_penalizes_runtime_and_content_redlines():
    a,t = fixture()
    t['devices'] = {d:{'captured':True,'open_failed':False,'readiness':{'scorable':True,'state':'ready'},'errors':[],'resource_failures':[]} for d in ('mobile','desktop')}
    a['compliance'] = [{'id':key,'status':'clear','reason':'Observed clear.','evidence_ids':['mobile-shot']} for key in ('sexual_content','real_money_gambling','drug_promotion')]
    clean=score_assessment(a,t)
    expected=round(clean['groups']['visual']['score']*.40+clean['groups']['information']['score']*.30+clean['groups']['adaptation']['score']*.30,2)
    assert clean['overall_score']==expected
    t['devices']['mobile']['errors']=['Test exception']
    faulty=score_assessment(a,t)
    assert faulty['overall_score']==round(expected-.8,2)
    a['compliance'][0]['status']='violation'
    assert score_assessment(a,t)['overall_score']==0
    a['compliance'][0]['status']='unknown'
    assert score_assessment(a,t)['overall_score'] is None


def test_scene_background_is_not_automatically_unused_layout_space():
    a,t=fixture()
    a['presentation']={'kind':'immersive_scene','reason':'Rendered game scene.','evidence_ids':['desktop-shot']}
    a['adjustments']=[adjustment('deduction','desktop_space_waste','scene-background','D2','desktop-shot')]
    r=score_assessment(a,t)
    assert item(r,'desktop')['score']==95
    assert any(e['decision']=='excluded_scene_context' for e in r['ledger']['entries'])


def test_scene_can_still_lose_points_for_evidenced_subject_readability():
    a,t=fixture()
    a['presentation']={'kind':'immersive_scene','reason':'Rendered game scene.','evidence_ids':['desktop-shot']}
    event=adjustment('deduction','desktop_space_waste','unreadable-house','D3','desktop-shot')
    event.update(task_impact='unreadable_subject',impact_reason='Required building details cannot be distinguished at the captured scale.')
    a['adjustments']=[event]
    assert item(score_assessment(a,t),'desktop')['score']==80


def test_scene_low_anchor_requires_a_specific_loss_not_merely_sparse_hud():
    a,t=fixture();a['presentation']={'kind':'immersive_scene','reason':'3D scene','evidence_ids':['desktop-shot']}
    row=next(r for r in a['items'] if r['id']=='desktop')
    row['quality'].update(execution='considered',reason='UI is sparse despite useful wide framing.')
    assert item(score_assessment(a,t),'desktop')['score'] is None
    row['layout_impact']={'type':'unreadable_subject','reason':'Required tiny building labels cannot be read.','evidence_ids':['desktop-shot']}
    assert item(score_assessment(a,t),'desktop')['score']==70


def test_holistic_creativity_can_use_direct_evidenced_refinements():
    a,t=fixture();row=next(r for r in a['items'] if r['id']=='creative_expression')
    row['quality'].update(execution='refined',reason='Integrated spatial scene.',refinements=['Long shadows define spatial depth.','Building form and lighting express a coherent theme.'])
    assert item(score_assessment(a,t),'creative_expression')['score']==85


def test_scene_positive_ordinary_anchor_is_not_a_false_layout_defect():
    a,t=fixture();a['presentation']={'kind':'immersive_scene','reason':'3D scene','evidence_ids':['desktop-shot']}
    row=next(r for r in a['items'] if r['id']=='desktop')
    row['quality'].update(execution='considered',reason='Wide framing retains useful environment and compact controls.')
    row['layout_impact']={'type':'none','reason':'No identified framing or operation loss.','evidence_ids':['desktop-shot']}
    assert item(score_assessment(a,t),'desktop')['score']==70
    row['quality']['reason']='UI is sparse despite useful wide framing.'
    assert item(score_assessment(a,t),'desktop')['score'] is None


def test_ordinary_typeface_alone_cannot_justify_a_deduction():
    a,t=fixture();event=adjustment('deduction','font_role_mismatch','default-font')
    event['observation']='Uses an ordinary font.';a['adjustments']=[event]
    r=score_assessment(a,t)
    assert item(r,'typography')['score']==95
    assert any(e['decision']=='excluded_typography_evidence' for e in r['ledger']['entries'])


def test_typography_can_lose_points_for_specific_reading_loss():
    a,t=fixture();event=adjustment('deduction','text_readability','tiny-title','D3')
    event.update(location='Top-left title',reading_loss='The title is too small to read at this viewport.')
    a['adjustments']=[event]
    assert item(score_assessment(a,t),'typography')['score']==80


def test_surface_effects_do_not_support_excellent_creativity_but_scene_expression_can():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='creative_expression')
    row['quality'].update(execution='refined',refinements=['CRT texture and green palette'])
    row['creative_scope']={'tier':'surface_style','domains':['style'],'reason':'Only a global surface treatment.','evidence_ids':['mobile-shot']}
    rules=policy_document(Settings())
    assert item(score_assessment(a,t,rules),'creative_expression')['score']==60
    row['creative_scope'].update(tier='distinctive_expression',domains=['imagery','spatial'],reason='Distinctive illustrated subjects and composition.')
    assert item(score_assessment(a,t,rules),'creative_expression')['score']==70
    row['creative_scope']['tier']='integrated_expression'
    assert item(score_assessment(a,t,rules),'creative_expression')['score']==85
    rules['creative_scope_caps']['surface_style']='considered'
    row['creative_scope']['tier']='surface_style'
    assert item(score_assessment(a,t,rules),'creative_expression')['score']==70


def test_missing_creative_scope_uses_conservative_cap_instead_of_empty_score():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='creative_expression')
    row.pop('creative_scope');row['quality'].update(execution='refined',refinements=['Surface texture'])
    assert item(score_assessment(a,t,policy_document(Settings())),'creative_expression')['score']==60


def test_readable_ordinary_fonts_use_readability_evidence_instead_of_unknown():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='typography')
    row['quality'].update(execution='considered',reason='层级清晰但字重常规',refinements=[])
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'typography')['score']==85
    row['checks'][0].update(verdict='unknown',evidence_ids=[])
    assert item(score_assessment(a,t,policy_document(Settings())),'typography')['score'] is not None


def test_core_desktop_usability_limits_score_even_with_optimistic_quality():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();desktop=next(i for i in a['items'] if i['id']=='desktop')
    rules=policy_document(Settings())
    desktop['usability']['level']='difficult'
    assert item(score_assessment(a,t,rules),'desktop')['score']==50
    desktop['usability']['level']='blocked'
    assert item(score_assessment(a,t,rules),'desktop')['score']==35


def test_evidenced_local_expression_is_not_zeroed_when_refinements_are_empty():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();creative=next(i for i in a['items'] if i['id']=='creative_expression')
    creative['quality'].update(execution='basic',refinements=[])
    creative['creative_scope'].update(tier='surface_style',reason='Illustrated mascot adds relevant emotion.')
    assert item(score_assessment(a,t,policy_document(Settings())),'creative_expression')['score']==50


def test_shared_desktop_scale_uses_independent_evidence_without_double_penalties():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();desktop=next(i for i in a['items'] if i['id']=='desktop')
    desktop['quality'].update(execution='competent',reason='桌面手牌与按钮过小')
    desktop['usability'].update(level='difficult',reason='Core ranks and targets difficult to use.')
    composition=next(i for i in a['items'] if i['id']=='composition')
    composition['quality'].update(execution='considered',reason='桌面端手牌偏小')
    composition['independent_quality']={'execution':'refined','reason':'Independent hierarchy and grouping are refined.','evidence_ids':['mobile-shot'],'refinements':['Coherent subject and HUD grouping']}
    composition['checks'][0].update(verdict='partial',reason='PC端手牌过小')
    a['adjustments']=[{**adjustment('deduction','wasted_composition','scale','D3','desktop-shot'),'observation':'桌面手牌过小'}]
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'desktop')['score']==50
    assert item(r,'composition')['score']==85
    assert item(r,'composition')['checks'][0]['verdict']=='excluded'
    assert any(e['decision']=='excluded_shared_desktop_loss' for e in r['ledger']['entries'])
    composition.pop('independent_quality')
    assert item(score_assessment(a,t,policy_document(Settings())),'composition')['score']==60


def test_same_style_effects_do_not_become_multiple_creative_dimensions():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='creative_expression')
    row['quality'].update(execution='refined',refinements=['Palette','CRT scanlines','Pixel font'])
    row['creative_scope'].update(tier='distinctive_expression',domains=['style','style','style'])
    assert item(score_assessment(a,t,policy_document(Settings())),'creative_expression')['score']==60


def test_independent_mobile_loss_is_not_excluded_by_device_word_in_another_clause():
    from evalapp.quickcheck.attribution import device_scale_claim,shared_desktop_loss
    assert not device_scale_claim('引导主体过小，独立于桌面问题仍存在构图松散')
    assert shared_desktop_loss('composition',{'quality':{'reason':'桌面端手牌偏小'}},[{'id':'desktop','quality':{'reason':'核心元素过小'}}])


def test_unobserved_interaction_state_does_not_block_visible_control_score():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='components')
    row['checks'][-1].update(verdict='unknown',reason='静态截图无法判断选中态',evidence_ids=[])
    scored=score_assessment(a,t,policy_document(Settings()))
    assert item(scored,'components')['score']==95
    assert item(scored,'components')['checks'][-1]['verdict']=='na'
    row['checks'][0].update(verdict='unknown',reason='核心控件未获取',evidence_ids=[])
    assert item(score_assessment(a,t,policy_document(Settings())),'components')['score'] is not None


def test_no_reading_loss_and_formal_hierarchy_difference_do_not_block_game_font():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='typography')
    row['quality'].update(execution='competent',reason='文字清晰，主要依赖系统默认表现',refinements=[])
    row['checks'][0].update(verdict='partial',reason='字号差异不大，靠位置区分')
    row['typography_impact']={'reading_loss':'none','reason':'文字清晰，无阅读障碍。'}
    result=score_assessment(a,t,policy_document(Settings()))
    assert item(result,'typography')['score']==85
    row['checks'][0]['reason']='正文过小且难读'
    assert item(score_assessment(a,t,policy_document(Settings())),'typography')['score'] is not None


def test_readable_but_unadapted_desktop_is_not_a_passing_layout():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();d=next(i for i in a['items'] if i['id']=='desktop')
    d['quality'].update(execution='competent',reason='Readable but mechanically narrow layout.')
    d['checks'][0].update(verdict='partial',reason='Wide layout remains unadapted.')
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'desktop')['score']==50
    assert item(r,'mobile')['score']==95
    assert r['groups']['adaptation']['score']==60
    assert r['groups']['adaptation']['aggregation']['weighted_score']==72.5


def test_limited_refinement_does_not_automatically_fail_a_good_layout():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();d=next(i for i in a['items'] if i['id']=='desktop')
    d['quality'].update(execution='considered',reason='Task scale is appropriate; minor density refinement.')
    d['checks'][0]['verdict']='partial'
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'desktop')['score']==70
    assert 'aggregation' not in r['groups']['adaptation']


def test_layout_limits_are_configurable_and_missing_auxiliary_check_preserves_primary_grade():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();d=next(i for i in a['items'] if i['id']=='desktop')
    d['quality']['execution']='competent';d['checks'][0]['verdict']='partial'
    settings=Settings();settings.scoring.device_layout_cap=None;settings.scoring.adaptation_failed_device_cap=None
    assert item(score_assessment(a,t,policy_document(settings)),'desktop')['score']==60
    d['checks'][0].update(verdict='unknown',evidence_ids=[])
    assert score_assessment(a,t,policy_document(Settings()))['groups']['adaptation']['score'] is not None


def test_praise_does_not_become_a_completion_gap_deduction():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='composition')
    row['quality'].update(execution='competent',reason='布局清晰，间距合理，主体明确')
    row['completion_gap']={'status':'none','reason':'未观察到具体不足'}
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'composition')['score']==60
    assert item(r,'composition')['deduction']==0
    assert not any(e['source']=='quality_anchor' and e['points']>0 for e in r['ledger']['entries'] if e.get('source'))
    row['completion_gap']={'status':'observed','reason':'Title overlaps the action row.','location':'Header','evidence_ids':['mobile-shot']}
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'composition')['score']==60
    assert item(r,'composition')['completion_gap']['reason']=='Title overlaps the action row.'
    assert item(r,'composition')['deduction']==0


def test_missing_rating_uses_observed_checkpoints_not_empty_or_invented_grade():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='composition');row.pop('quality')
    row['checks'][0].update(verdict='no',reason='Subject is covered by the foreground panel.')
    r=score_assessment(a,t,policy_document(Settings()))
    assert item(r,'composition')['score']==60
    assert item(r,'composition')['deduction']==20
    assert item(r,'composition')['scoring_source']=='checkpoint_fallback'


def test_absence_of_gap_does_not_prove_exceptional_quality():
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    a,t=fixture();row=next(i for i in a['items'] if i['id']=='composition')
    row['quality'].update(execution='competent',reason='Basic hierarchy and consistent spacing.',refinements=[])
    row['completion_gap']={'status':'none'}
    result=score_assessment(a,t,policy_document(Settings()))
    assert item(result,'composition')['score']==60
    row['quality'].update(execution='refined',reason='Specific refined composition.',refinements=['Precisely balanced foreground and task hierarchy'])
    assert item(score_assessment(a,t,policy_document(Settings())),'composition')['score']==85
    row['quality'].update(execution='exceptional',refinements=[])
    assert item(score_assessment(a,t,policy_document(Settings())),'composition')['score']==60
