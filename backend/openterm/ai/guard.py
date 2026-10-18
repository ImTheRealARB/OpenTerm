"""Loop guard (idea ported from Vibe-Trading's agent loop): stop after repeated failed or empty tool calls or a repeated identical call."""

from __future__ import annotations

import json

MAX_FAILS = 3
MAX_REPEATS = 2


def canon(name: str, args: dict) -> str:
    return name + json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))


class LoopGuard:
    def __init__(self, max_fail: int = MAX_FAILS, max_repeat: int = MAX_REPEATS):
        self.max_fail = max_fail
        self.max_repeat = max_repeat
        self.fails = 0
        self.seen: dict[str, int] = {}

    def before(self, name: str, args: dict) -> str | None:
        """A reason to refuse this call (the same call has already run `max_repeat` times), else None."""
        key = canon(name, args)
        if self.seen.get(key, 0) >= self.max_repeat:
            return f"THE SAME {name.upper()} CALL WAS REPEATED {self.max_repeat} TIMES"
        self.seen[key] = self.seen.get(key, 0) + 1
        return None

    def after(self, ok: bool, empty: bool) -> str | None:
        """Record one result; a reason to stop after `max_fail` failed or empty results in a row."""
        self.fails = 0 if ok and not empty else self.fails + 1
        if self.fails >= self.max_fail:
            return f"{self.max_fail} FAILED OR EMPTY TOOL CALLS IN A ROW"
        return None
