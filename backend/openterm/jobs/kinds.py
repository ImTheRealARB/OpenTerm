"""Job kinds. A kind is a top-level function `fn(params, progress) -> dict` run inside a worker process.

`progress(fraction, message)` reports 0..1 and raises JobCancelled once the job was asked to stop. Heavy libraries are
imported inside `fn`, never at module level (the server imports this module to validate params).
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field


class JobCancelled(Exception):
    pass


class BadParams(ValueError):
    pass


@dataclass(frozen=True)
class Kind:
    name: str
    version: str
    label: str
    fn: Callable[[dict, Callable[[float, str], None]], dict]
    validate: Callable[[dict], dict]
    time_limit_s: float = 300.0
    fingerprint: Callable[[dict], str] = field(default=lambda _params: "")


def _int(params: dict, key: str, lo: int, hi: int, default: int | None = None) -> int | None:
    v = params.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BadParams(f"{key.upper()} MUST BE AN INTEGER {lo}-{hi}")
    return v


# --- sleep: test / demo job (labelled TEST JOB) -----------------------------------------------------------------

SLEEP_KEYS = {"steps", "step_ms", "fail_at", "crash_at", "ignore_cancel", "tag"}


def validate_sleep(params: dict) -> dict:
    if not isinstance(params, dict):
        raise BadParams("PARAMS MUST BE AN OBJECT")
    extra = set(params) - SLEEP_KEYS
    if extra:
        raise BadParams(f"UNKNOWN PARAMS {', '.join(sorted(extra)).upper()}")
    out = {"steps": _int(params, "steps", 1, 10_000, 20), "step_ms": _int(params, "step_ms", 0, 600_000, 100)}
    for k in ("fail_at", "crash_at"):
        if (v := _int(params, k, 0, 10_000)) is not None:
            out[k] = v
    if "ignore_cancel" in params:
        if not isinstance(params["ignore_cancel"], bool):
            raise BadParams("IGNORE_CANCEL MUST BE TRUE OR FALSE")
        out["ignore_cancel"] = params["ignore_cancel"]
    if "tag" in params:
        if not isinstance(params["tag"], str) or len(params["tag"]) > 64:
            raise BadParams("TAG MUST BE A SHORT STRING")
        out["tag"] = params["tag"]
    return out


def sleep_job(params: dict, progress: Callable[[float, str], None]) -> dict:
    steps, step_s = params["steps"], params["step_ms"] / 1000
    for i in range(steps):
        if params.get("crash_at") == i:
            os._exit(3)  # simulates a worker dying mid-job (tests)
        if params.get("fail_at") == i:
            raise RuntimeError(f"fail_at step {i}")
        time.sleep(step_s)
        if not params.get("ignore_cancel"):  # ignore_cancel: a job that never checks in (hard-cancel test)
            progress((i + 1) / steps, f"step {i + 1}/{steps}")
    return {"steps": steps, "step_ms": params["step_ms"]}


KINDS: dict[str, Kind] = {
    "sleep": Kind("sleep", "1", "TEST JOB", sleep_job, validate_sleep),
}
