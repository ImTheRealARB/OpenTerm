"""Phase 21: the drawing store accepts the new tools and the optional label / hidden / locked fields, still refuses
unknown fields, and its anchor table matches the frontend's `TOOLS` table (one list, two languages)."""

import re
from pathlib import Path

import pytest

from openterm.drawings import POINTS, validate
from openterm.userdata import UserDataError

TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "chart" / "drawings.ts"


def test_anchor_table_mirrors_the_frontend():
    text = TS.read_text(encoding="utf-8")
    block = text[text.index("export const TOOLS"):text.index("};", text.index("export const TOOLS"))]
    ts = {k: (int(lo), int(hi)) for k, lo, hi in re.findall(r"(\w+): \{ name: \"[^\"]+\", min: (\d+), max: (\d+)", block)}
    assert ts == POINTS


def test_new_tools_and_optional_fields_round_trip(client):
    path = {"id": "p1", "kind": "PATH", "pts": [{"t": 1, "p": 1}, {"t": 2, "p": 2}, {"t": 3, "p": 1}], "label": "zig", "hidden": True}
    long = {"id": "l1", "kind": "LONG", "pts": [{"t": 1, "p": 100}, {"t": 2, "p": 95}, {"t": 3, "p": 115}], "label": "100000 1", "locked": False}
    r = client.put("/api/drawings/AAPL", json={"drawings": [path, long]})
    assert r.status_code == 200, r.text
    assert client.get("/api/drawings/AAPL").json()["drawings"] == [path, long]


@pytest.mark.parametrize("bad", [
    {"id": "x", "kind": "PATH", "pts": [{"t": 1, "p": 1}] * 11},  # more than 10 anchors
    {"id": "x", "kind": "TEXT", "pts": [{"t": 1, "p": 1}], "label": "x" * 201},
    {"id": "x", "kind": "TEXT", "pts": [{"t": 1, "p": 1}], "hidden": "yes"},
    {"id": "x", "kind": "TEXT", "pts": [{"t": 1, "p": 1}], "colour": "red"},  # unknown field
])
def test_bad_new_drawings_are_refused(bad):
    with pytest.raises(UserDataError):
        validate([bad])
