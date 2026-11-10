"""Example extension for OpenTerm. Read docs/EXTENSIONS.md first.

An extension is a module with `register(api)`. It runs inside OpenTerm with the permissions of the user who started it, so only
enable code you trust. This one touches no files, keys or network, and its numbers are computed here (they are not market data).
"""

import math
import time


def main(args: list[str]) -> dict:
    """EXT hello [NAME]: a table payload."""
    who = args[0] if args else "world"
    return {
        "kind": "table",
        "title": "HELLO EXTENSION",
        "columns": [{"key": "what", "title": "WHAT"}, {"key": "value", "title": "VALUE", "kind": "num"}, {"key": "note", "title": "NOTE"}],
        "rows": [
            {"what": f"hello {who}", "value": 1.0, "note": "text cell"},
            {"what": "pi", "value": math.pi, "note": "number cell, 2 decimals"},
            {"what": "missing", "value": None, "note": "null prints as a dash, never as a made-up number"},
        ],
        "notes": ["EXAMPLE DATA: computed by the hello extension, not market data."],
    }


def wave(args: list[str]) -> dict:
    """EXT hello wave [DAYS]: a series payload (epoch seconds ascending, one value each)."""
    days = int(args[0]) if args and args[0].isdigit() else 60
    days = max(2, min(days, 365))
    end = int(time.time()) // 86400 * 86400
    t = [end - (days - 1 - i) * 86400 for i in range(days)]
    return {"kind": "series", "title": f"HELLO WAVE {days}D (COMPUTED SINE)", "unit": "units", "t": t,
            "v": [round(math.sin(i / 7), 4) for i in range(days)]}


def greet(args: dict) -> dict:
    """Tool ext.hello.greet: read-only, returns a small dict (the result is cut to 6,000 characters)."""
    return {"greeting": f"hello {args.get('name') or 'world'}"}


def register(api) -> None:
    api.add_route("main", main, title="Hello table", args="[NAME]")
    api.add_route("wave", wave, title="Computed sine series", args="[DAYS]")
    api.add_tool(
        "greet", "Greets a name. A demo tool that reads nothing.",
        {"properties": {"name": {"type": "string", "description": "who to greet"}}}, greet,
    )
