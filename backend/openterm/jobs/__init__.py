"""Background jobs (Phase 11): worker processes, progress over /ws, results cached by hash.

Kept import-light: worker processes import this package, so nothing here may pull in FastAPI, aiosqlite or numpy.
The runner lives in `jobs/runner.py` and is imported by the server only.
"""

import hashlib

import orjson


def job_hash(kind: str, version: str, params: dict, fingerprint: str = "") -> str:
    """Same kind + version + params (any key order) + data fingerprint = same hash = cached result."""
    blob = orjson.dumps([kind, version, params, fingerprint], option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(blob).hexdigest()
