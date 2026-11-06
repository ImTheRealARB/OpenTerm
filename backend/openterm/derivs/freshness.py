"""Freshness bookkeeping for the derivatives functions (audit B-2).

A derivatives function reads several cached inputs (an option chain, the Treasury curve, a spot quote, a futures
contract). Each comes back from DataService in an envelope that says how old it is, whether it is stale and which
sources failed first. The functions used to keep only the `data` part and then stamp their own answer "fresh, age 0",
so a day-old chain served while Yahoo was down looked live. "Never fake data" forbids that.

Now every place that opens an input envelope calls `note(env)`. `Derivs.run` collects those notes for one request
(a ContextVar: a variable whose value is private to the current request, even across asyncio tasks) and `stamp` folds
them into the answer the way DataService.macro does: the OLDEST `as_of`, `stale` if ANY input was stale, and the
union of `fallback_from` / `fallback_notes`.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_NOTES: ContextVar[list[dict] | None] = ContextVar("derivs_input_notes", default=None)


def note(env: object) -> None:
    """Record one input envelope for the request in progress (a no-op outside `collect`)."""
    notes = _NOTES.get()
    if notes is not None and isinstance(env, dict) and "as_of" in env:
        notes.append(env)


@contextmanager
def collect() -> Iterator[list[dict]]:
    notes: list[dict] = []
    token = _NOTES.set(notes)
    try:
        yield notes
    finally:
        _NOTES.reset(token)


def summarize(envs: list[dict]) -> dict | None:
    """One envelope-shaped summary (as_of, stale, fallback_from, fallback_notes) of several inputs; None for none."""
    if not envs:
        return None
    as_of = min(e["as_of"] for e in envs)
    fallback = list(dict.fromkeys(f for e in envs for f in e.get("fallback_from") or []))
    notes: dict = {}
    for e in envs:
        notes.update(e.get("fallback_notes") or {})
    out = {"as_of": as_of, "stale": any(bool(e.get("stale")) for e in envs), "fallback_from": fallback}
    if notes:
        out["fallback_notes"] = notes
    return out


def stamp(result: dict, notes: list[dict]) -> dict:
    """Fold the inputs' freshness into a finished answer."""
    if not notes:
        return result
    merged = summarize([*notes, result] if "as_of" in result else notes)
    assert merged is not None
    return {**result, **merged, "age_s": round(time.time() - merged["as_of"], 2)}
