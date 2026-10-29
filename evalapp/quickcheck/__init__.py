"""Public QuickCheck API: evaluate a URL, or replay a sealed assessment."""
import asyncio
from .config import Settings, ModelConfig, ApplicationConfig, load_config
from .replay import replay_record

__version__ = '0.1.0'
__all__ = ['Settings', 'ModelConfig', 'ApplicationConfig', 'load_config',
           'evaluate', 'evaluate_async', 'replay_record']

async def evaluate_async(url, *, name=None, project_id=None, settings=None,
                         output_dir=None, snapshot_id=None):
    """Evaluate one URL; snapshot_id reuses evidence but still calls the model.

    Results use schema_version 4.0. status is completed, partial or failed;
    an unknown score remains None. Cancellation propagates to the caller.
    No application config is read implicitly. Supply Settings explicitly.
    """
    from .orchestrator import evaluate_async as run
    return await run(url, name=name, projectId=project_id, settings=settings,
                     output_dir=output_dir, snapshot_id=snapshot_id)

def evaluate(url, **kwargs):
    """Blocking counterpart; use evaluate_async inside an existing event loop."""
    return asyncio.run(evaluate_async(url, **kwargs))
