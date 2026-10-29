from evalapp.quickcheck.browser import navigation_readiness


def test_navigation_timeout_preserves_repeated_rendered_ready_content():
    ready={'state':'animated_content','scorable':True,'sample_count':3,'fonts_pending':True}
    final={'meaningful':True,'loading_visible':False,'document_state':'interactive','fonts_ready':False}
    result=navigation_readiness(ready,final,True)
    assert result['scorable'] and result['state']=='animated_content'
    assert result['navigation_timed_out'] and result['fonts_pending']
    assert 'navigation_timed_out' not in ready


def test_timeout_does_not_promote_blank_or_loading_page_to_ready():
    for state in ('persistent_loading','confirmed_blank_screen','unsettled'):
        result=navigation_readiness({'state':state,'scorable':False,'sample_count':3},{'meaningful':False,'loading_visible':True,'document_state':'interactive'},True)
        assert not result['scorable']
        if state!='unsettled':assert result['state']==state


def test_a_single_early_frame_cannot_bypass_navigation_failure():
    result=navigation_readiness({'state':'stable','scorable':True,'sample_count':1},{'meaningful':True,'loading_visible':False,'document_state':'interactive'},True)
    assert not result['scorable']
