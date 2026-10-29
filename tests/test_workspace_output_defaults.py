from pathlib import Path
from click.testing import CliRunner
from evalapp.config import Config


def test_configured_shared_root_has_separate_output_namespaces(tmp_path):
    config=Config(workspace_root=str(tmp_path))
    assert config.quickcheck_workspace_path==tmp_path/'quickcheck'
    assert config.artifact_workspace_path==tmp_path/'evaluations'


def test_quickcheck_cli_uses_shared_root_and_respects_explicit_output(tmp_path,monkeypatch):
    import evalapp.commands.quickcheck as module
    captured=[]
    monkeypatch.setattr(module,'evaluate',lambda *args,**kwargs:captured.append(kwargs['output_dir']) or {'status':'test'})
    config=Config(workspace_root=str(tmp_path))
    result=CliRunner().invoke(module.quickcheck_cmd,['--url','https://example.com'],obj={'config':config})
    assert result.exit_code==0 and Path(captured[-1])==tmp_path/'quickcheck'
    custom=tmp_path/'custom'
    result=CliRunner().invoke(module.quickcheck_cmd,['--url','https://example.com','--output',str(custom)],obj={'config':config})
    assert result.exit_code==0 and Path(captured[-1])==custom


def test_direct_artifact_output_uses_shared_root_and_respects_override(tmp_path,monkeypatch):
    import evalapp.commands._artifact_prep as prep
    from evalapp.commands.evaluate import evaluate_cmd
    outputs=[]
    monkeypatch.setattr(prep,'prepare_artifact_workspace',lambda output,*args,**kwargs:outputs.append(output) or 'web')
    monkeypatch.setattr(prep,'discover_and_build_tasks',lambda *args:([],[]))
    config=Config(workspace_root=str(tmp_path))
    result=CliRunner().invoke(evaluate_cmd,['--url','https://example.com','--sample-ids','sample'],obj={'config':config})
    assert result.exit_code==0 and outputs[-1]==tmp_path/'evaluations'
    custom=tmp_path/'custom-full'
    result=CliRunner().invoke(evaluate_cmd,['--url','https://example.com','--sample-ids','sample','--output',str(custom)],obj={'config':config})
    assert result.exit_code==0 and outputs[-1]==custom


def test_python_repository_default_uses_configured_root(tmp_path,monkeypatch):
    from evalapp.quickcheck.repository import EvaluationRepository
    import evalapp.quickcheck.paths as paths
    monkeypatch.setattr(paths,'default_output_dir',lambda:tmp_path/'quickcheck')
    assert EvaluationRepository().root==tmp_path/'quickcheck'
