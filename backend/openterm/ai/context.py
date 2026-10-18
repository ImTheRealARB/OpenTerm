"""Context budget: tool results are cut to a fixed size and old turns are dropped oldest-first (tool results before whole turns)."""

from __future__ import annotations

RESULT_LIMIT = 6000
BUDGET_TOKENS = 24000
DROPPED = "[RESULT DROPPED TO FIT THE CONTEXT BUDGET]"


def truncate_text(text: str, limit: int = RESULT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.65), int(limit * 0.25)
    cut = len(text) - head - tail
    return f"{text[:head]}\n...{cut} CHARACTERS OMITTED...\n{text[-tail:]}"


def estimate_tokens(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        n += len(str(m.get("content") or ""))
        for c in m.get("tool_calls") or []:
            n += len(str(c.get("function") or ""))
    return n // 4 + 4 * len(messages)


def _turns(messages: list[dict]) -> list[list[dict]]:
    """Split after the system message into turns: each starts at a user message."""
    turns: list[list[dict]] = []
    for m in messages:
        if m.get("role") == "system":
            continue
        if m.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(m)
    return turns


def fit(messages: list[dict], budget: int = BUDGET_TOKENS) -> list[dict]:
    if estimate_tokens(messages) <= budget:
        return messages
    messages = [dict(m) for m in messages]  # the caller's list is not edited
    system = [m for m in messages if m.get("role") == "system"]
    turns = _turns(messages)
    # 1. blank the oldest tool results (the call stays, so the protocol stays valid), never the current turn's
    for turn in turns[:-1] + [turns[-1]]:
        for m in turn:
            if m.get("role") == "tool" and m.get("content") != DROPPED:
                m["content"] = DROPPED
                if estimate_tokens(system + [x for t in turns for x in t]) <= budget:
                    return system + [x for t in turns for x in t]
    # 2. drop whole old turns, keeping the last one
    while len(turns) > 1 and estimate_tokens(system + [x for t in turns for x in t]) > budget:
        turns.pop(0)
    return system + [x for t in turns for x in t]
