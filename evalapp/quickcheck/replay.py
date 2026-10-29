"""Deterministic harness replay; never captures pages or requests a model."""
from __future__ import annotations
import time
from .repository import EvaluationRepository,read_json
from .policy import policy_document,VERSION
from .completion import normalize,missing_fields
from .score_worker import score_assessment


def replay_record(evaluation_id, *, settings, output_dir):
    repository=EvaluationRepository(output_dir)
    source=repository.result(evaluation_id)
    folder=repository.root/'runs'/evaluation_id
    assessment=normalize(read_json(folder/'assessment.json'))
    snapshot=repository.snapshot(source['snapshot_id'])
    technical=read_json(snapshot.root/'technical.json')
    request={k:source.get(k) for k in ('url','name','projectId')}
    policy=policy_document(settings)
    run=repository.create_run(request,policy,snapshot_id=snapshot.id)
    began=time.monotonic()
    try:
        run.phase('scoring')
        run.write('assessment.json',assessment)
        for filename in ('assessment.raw.json','completion.json','evidence_aliases.json'):
            if (folder/filename).is_file():run.write(filename,read_json(folder/filename))
        missing=missing_fields(assessment,technical)
        run.write('contract.json',{'adapter':'wire-v2','replayed_from':evaluation_id,'missing':missing})
        scored=score_assessment(assessment,technical,policy)
        complete=all(g['status'] in {'completed','not_applicable'} for g in scored['groups'].values())
        manifest=read_json(run.root/'manifest.json')
        result={**source,**scored,'evaluation_id':run.id,'case_id':manifest['case_id'],'policy_id':manifest['policy_id'],
                'status':'completed' if complete else 'partial','outcome':'completed' if complete else 'evidence_or_contract_incomplete',
                'replayed_from':evaluation_id,'replay_kind':'contract_and_scoring','reused_assessment':True,'offline_replay':True,
                'source_duration_ms':source.get('source_duration_ms') if source.get('reused_assessment') else source.get('duration_ms'),
                'duration_ms':round((time.monotonic()-began)*1000),
                'review':{**source.get('review',{}),'validation_warnings':scored['ledger']['warnings']},
                'quality_rubric':{'version':VERSION},
                'versions':{**source.get('versions',{}),'rules':VERSION,'policy_sha256':manifest['policy_id'][7:]}}
        result.pop('ledger',None)
        result['replay_timings_ms']={'contract_and_scoring':result['duration_ms']}
        run.write('stage_timings.json',{'recorded_evaluation':source.get('timings_ms',{}),'local_replay':result['replay_timings_ms']})
        run.finish(result,scored['ledger'])
        return result
    except BaseException:
        run.phase('failed')
        raise
    finally:
        run.close()
