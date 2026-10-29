"""Bounded evaluation harness: lossless wire adapters and observable stage budgets."""
from __future__ import annotations
import copy
import time
from contextlib import contextmanager


class StageTimer:
    def __init__(self):
        self.values = {}

    @contextmanager
    def measure(self, stage):
        began = time.monotonic()
        try:
            yield
        finally:
            self.values[stage] = self.values.get(stage, 0) + round((time.monotonic() - began) * 1000)


def canonical_rows(value, fields=None):
    """Accept list or id-keyed objects without inventing or replacing judgments."""
    if isinstance(value, list):
        return copy.deepcopy(value)
    if not isinstance(value, dict):
        return []
    rows = []
    for key, row in value.items():
        if isinstance(row, dict):
            rows.append({'id': key, **copy.deepcopy(row)})  # conflicting explicit ids stay visible
        elif fields and isinstance(row, list) and len(row) == len(fields):
            rows.append({'id': key, **dict(zip(fields, copy.deepcopy(row)))})
        else:
            rows.append({'id': key, '_invalid_wire_value': copy.deepcopy(row)})
    return rows


class EvidenceCodec:
    """Short wire ids; all persisted assessments use the original sealed ids."""
    def __init__(self, catalog):
        self.forward = {row['id']: f'@e{i}' for i, row in enumerate(catalog)}
        self.backward = {v: k for k, v in self.forward.items()}

    def _map(self, value, mapping):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [self._map(v, mapping) for v in value]
        if isinstance(value, dict):
            return {k: self._map(v, mapping) for k, v in value.items()}
        return value

    def encode(self, value):
        return self._map(value, self.forward)

    def decode(self, value):
        return self._map(value, self.backward)


def initial_budget(seconds):
    """Keep a small completion reserve, not 30% of every successful request."""
    return max(.1, seconds - min(15., seconds * .15))
