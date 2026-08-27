"""Service layer - business orchestration and persistence coordination.

This layer sits between Commands and Runner, hosting business logic
extracted from the commands layer:
- EvaluationService: Evaluation data persistence (evaluation.json, scores.json, backend_trace.json)
- ReportService: Report generation orchestration (screenshot extraction, score writing, HTML rendering)
- aesthetics: Unified aesthetics scoring entry point (eliminates duplicate logic in evaluate/report)
"""

from .reporting import ReportService
from .evaluation import EvaluationService
from .aesthetics import AestheticsService, load_rules, score_sample

__all__ = [
    "ReportService",
    "EvaluationService",
    "AestheticsService",
    "load_rules",
    "score_sample",
]
