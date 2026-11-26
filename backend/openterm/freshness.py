"""Freshness bookkeeping for every view built from other cached answers (audit B-2, then audit G3: H-16 and C-07).

A view (a derivatives function, a macro board, QRY, a fundamentals table) reads several cached inputs. Each comes back
from DataService in an envelope that says how old it is, whether it is stale and which sources failed first. A view used
to keep only the `data` part and then stamp its own answer "fresh, age 0", so a day-old chain served while Yahoo was down
looked live. "Never fake data" forbids that.

`service.envelope()` calls `note(env)` for every envelope it builds, so no call site has to remember. Whoever combines
inputs opens a `collect()` scope (a ContextVar: a variable whose value is private to the current request, even across
asyncio tasks) and folds what it saw into its answer:
  - `stamp(result, notes)` for an answer returned as it is (Derivs.run, Fund.run, QRY);
  - `fold(value, notes)` for a value that `DataService.swr` is about to cache (every view service): the cached value keeps
    `stale` and the oldest `as_of`, so a later read does not hand it out as fresh.
Both take the OLDEST `as_of`, `stale` if ANY input was stale, and the union of `fallback_from` / `fallback_notes`.
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


def fold(value: dict, notes: list[dict]) -> dict:
    """Fold the inputs' freshness into a value about to be cached by `DataService.swr` (shape {"data", "source", ...}).
    Adds `as_of` (oldest input) and `stale` (any input) only when something was read; `envelope()` and `swr` honour both."""
    if not notes:
        return value
    merged = summarize(notes)
    assert merged is not None
    fallback = list(dict.fromkeys([*(value.get("fallback_from") or []), *merged["fallback_from"]]))
    out = {**value, "as_of": merged["as_of"], "fallback_from": fallback}
    if merged["stale"]:
        out["stale"] = True
    if merged.get("fallback_notes"):
        out["fallback_notes"] = {**merged["fallback_notes"], **(value.get("fallback_notes") or {})}
    return out
