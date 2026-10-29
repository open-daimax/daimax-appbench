from evalapp.quickcheck.repository import EvaluationRepository


def test_same_url_has_one_card_with_latest_result_regardless_of_name_or_project(tmp_path, monkeypatch):
    repo=EvaluationRepository(tmp_path)
    rows=[{'case_id':'new','evaluation_id':'qc_new','url':'https://example.com/app#/home','name':'重评','projectId':'inferred'},
          {'case_id':'old','evaluation_id':'qc_old','url':'https://example.com/app#/home','name':None,'projectId':None},
          {'case_id':'route','evaluation_id':'qc_route','url':'https://example.com/app#/settings'}]
    monkeypatch.setattr(repo,'runs',lambda:rows)
    cases=repo.cases()
    assert len(cases)==2
    assert cases[0]['latest']['evaluation_id']=='qc_new'
    assert cases[0]['name']=='重评' and cases[0]['run_count']==2
    assert rows[1]['evaluation_id']=='qc_old'


def test_late_finishing_old_run_cannot_replace_newer_submission(tmp_path, monkeypatch):
    repo=EvaluationRepository(tmp_path)
    rows=[{'case_id':'old','url':'https://example.com','evaluation_id':'old','_submitted_at':1,'_stored_at':10},
          {'case_id':'new','url':'https://example.com','evaluation_id':'new','_submitted_at':2,'_stored_at':5}]
    monkeypatch.setattr(repo,'runs',lambda:rows)
    assert repo.cases()[0]['latest']['evaluation_id']=='new'
