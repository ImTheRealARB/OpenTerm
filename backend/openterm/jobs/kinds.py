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
    internal: bool = False
    hash_view: Callable[[dict], dict] = field(default=lambda params: params)
    """The part of params that identifies the work (bt.run leaves out its display labels, e.g. data age)."""
    """Submitted only by the server (e.g. bt.run via /api/bt/run), never through POST /api/jobs."""


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


# --- bt.run: one backtest (Phase 12). Params are built by /api/bt/run; the data file hash is the fingerprint. ----

BT_KEYS = {"data_path", "data_sha", "rule", "code", "short", "engine", "config", "bars_per_year", "adjusted",
           "time_limit_s", "memory_limit_mb", "labels", "meta", "run_id", "structure"}


def validate_bt(params: dict) -> dict:
    if not isinstance(params, dict) or set(params) - BT_KEYS or not {"data_path", "data_sha", "engine", "config",
                                                                     "run_id"} <= set(params):
        raise BadParams("BT.RUN PARAMS ARE BUILT BY /api/bt/run")
    if params["engine"] == "options":
        if params.get("rule") or params.get("code") or not params.get("structure"):
            raise BadParams("BT.RUN OPTIONS NEEDS A STRUCTURE AND NO RULE OR CODE")
    elif bool(params.get("rule")) == bool(params.get("code")):
        raise BadParams("BT.RUN NEEDS EXACTLY ONE OF RULE OR CODE")
    return params


def bt_job(params: dict, progress: Callable[[float, str], None]) -> dict:
    from ..bt.job import run  # pandas loads here, in the worker

    return run(params, progress)


# --- bt.mc / bt.wf: validation of a stored run (Phase 12 step 6). Params are built by /api/bt/runs/{id}/mc|wf. ----

VAL_COMMON = {"run_id", "initial_cash", "bars_per_year", "equity", "trades", "labels"}
VAL_KEYS = {
    "bt.mc": VAL_COMMON | {"n_simulations", "n_bootstrap", "confidence", "seed"},
    "bt.wf": VAL_COMMON | {"n_windows"},
}


def validate_bt_val(kind: str):
    def validate(params: dict) -> dict:
        if not isinstance(params, dict) or set(params) != VAL_KEYS[kind]:
            raise BadParams(f"{kind.upper()} PARAMS ARE BUILT BY /api/bt/runs/{{id}}/{kind[3:]}")
        return params

    return validate


def bt_mc_job(params: dict, progress: Callable[[float, str], None]) -> dict:
    from ..bt.validate_job import monte_carlo  # pandas loads here, in the worker

    return monte_carlo(params, progress)


def bt_wf_job(params: dict, progress: Callable[[float, str], None]) -> dict:
    from ..bt.validate_job import walk_forward

    return walk_forward(params, progress)


KINDS: dict[str, Kind] = {
    "sleep": Kind("sleep", "1", "TEST JOB", sleep_job, validate_sleep),
    "bt.run": Kind("bt.run", "1", "BACKTEST", bt_job, validate_bt, time_limit_s=60.0,
                   fingerprint=lambda p: p["data_sha"], internal=True,
                   hash_view=lambda p: {k: v for k, v in p.items() if k != "labels"}),
    "bt.mc": Kind("bt.mc", "1", "MONTE CARLO", bt_mc_job, validate_bt_val("bt.mc"), time_limit_s=60.0, internal=True,
                  hash_view=lambda p: {k: v for k, v in p.items() if k != "labels"}),
    "bt.wf": Kind("bt.wf", "1", "WALK-FORWARD", bt_wf_job, validate_bt_val("bt.wf"), time_limit_s=60.0, internal=True,
                  hash_view=lambda p: {k: v for k, v in p.items() if k != "labels"}),
}
