"""Finance playbooks as prompt files (`skills/*.md`). The agent loads one with the `skill` tool and finds one with the `skills` tool.

Five playbooks are written by hand. The rest are ported from Vibe-Trading by `scripts/port_vibe_skills.py` (MIT, see THIRD_PARTY.md); a ported file
starts with an HTML comment naming its source file and commit. The comment is for people and audits: it is not sent to the model.
Every playbook only names tools that exist in `tools.REGISTRY` (a pytest checks this for every file).

A long playbook is read in pieces: `read(name, section)` returns one `##` or `###` heading with everything under it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DIR = Path(__file__).parent / "skills"

# The tool result is cut at 6,000 characters after JSON escaping (context.RESULT_LIMIT). Playbook text stays well under that so
# the cut never lands inside a playbook: the escaped result of any playbook or section is checked in test_phase20_skills.py.
MAX_CHARS = 4000
OUTLINE_CHARS = 900  # room for the list of headings that is returned next to a long playbook
RESULT_JSON_MAX = 5700  # the escaped JSON of one result; below the 6,000 cut so the cut never lands inside a playbook
INDEX_WIDTH = 80  # a description in the skills search result is cut to this many characters

_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)
_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*#*\s*$")


def names() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.md"))


# path -> ((mtime_ns, size), text, sha256 hex). Every AI run fingerprints every playbook for its audit manifest; re-reading and
# re-hashing ~60 files (and listing the folder once per file) cost several ms per run. A file is read again only when its
# modification time or size changes, so an edited playbook is never fingerprinted from a stale copy.
_FILES: dict[str, tuple[tuple[int, int], str, str]] = {}


def _load(path: Path) -> tuple[str, str]:
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _FILES.get(str(path))
    if hit is None or hit[0] != stamp:
        raw = path.read_text(encoding="utf-8")
        hit = _FILES[str(path)] = (stamp, raw, hashlib.sha256(raw.encode("utf-8")).hexdigest())
    return hit[1], hit[2]


def get(name: str) -> str | None:
    """The raw file (header comment included), or None. Only known file stems are read, which also blocks path tricks."""
    if name not in names():
        return None
    return _load(DIR / f"{name}.md")[0]


def digests() -> dict[str, str]:
    """sha256 of every playbook's raw file, by name (one folder listing; unchanged files are not read again). For the audit manifest."""
    return {n: _load(DIR / f"{n}.md")[1] for n in names()}


def text(name: str) -> str | None:
    """The playbook as the model sees it: the file without its leading source comment."""
    raw = get(name)
    return None if raw is None else _COMMENT.sub("", raw, count=1).strip("\n") + "\n"


def describe(name: str, width: int = INDEX_WIDTH) -> str:
    """One short line about a playbook: its `Goal:` line, cut to `width` characters at a word boundary."""
    body = text(name) or ""
    m = re.search(r"^Goal:\s*(.+)$", body, re.MULTILINE)
    line = (m.group(1) if m else body.splitlines()[0] if body else "").strip()
    line = re.sub(r"\s+", " ", line)
    if len(line) <= width:
        return line
    cut = line[: width - 3].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "..."


def _norm(title: str) -> str:
    return re.sub(r"[\s`*_:]+", " ", title).strip().lower()


def _headings(body: str) -> list[tuple[int, str, int]]:
    """(level, title, line index) of every `##`-`####` heading, ignoring `#` comment lines inside code fences.
    A title that appears again gets ' (2)', ' (3)' ..., so every heading can be asked for by name."""
    out, fenced, seen = [], False, {}
    for i, line in enumerate(body.splitlines()):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and (m := _HEADING.match(line)):
            title = m.group(2).strip()
            seen[_norm(title)] = n = seen.get(_norm(title), 0) + 1
            out.append((len(m.group(1)), title if n == 1 else f"{title} ({n})", i))
    return out


def sections(name: str) -> list[str]:
    """Headings (`##` and `###`) that `read` accepts as a section, in file order."""
    body = text(name) or ""
    return [t for lvl, t, _ in _headings(body) if lvl <= 3]


def _cut(body: str, limit: int) -> tuple[str, bool]:
    """Cut at a line boundary at or under `limit` characters. Returns (text, was_cut)."""
    if len(body) <= limit:
        return body, False
    cut = body[:limit].rsplit("\n", 1)[0]
    return cut.rstrip() + "\n", True


def _titles(heads: list[tuple[int, str, int]], limit: int = OUTLINE_CHARS) -> list[str]:
    """Heading titles (each at most 60 characters) until their total reaches `limit` characters."""
    out, used = [], 0
    for _, t, _ in heads:
        t = t[:60]
        if used + len(t) + 3 > limit:
            break
        out.append(t)
        used += len(t) + 3
    return out


def _fit(out: dict) -> dict:
    """Shorten the playbook text of `out` (at a line boundary) until its JSON is under RESULT_JSON_MAX characters."""
    while len(json.dumps(out, separators=(",", ":"))) > RESULT_JSON_MAX and len(out["playbook"]) > 200:
        out["playbook"], _ = _cut(out["playbook"], int(len(out["playbook"]) * 0.9))
        out["truncated"] = True
    return out


def read(name: str, section: str | None = None) -> dict:
    """What the `skill` tool returns. Raises KeyError for an unknown playbook. An unknown section is information for the model: the answer
    carries an `error` and the list of valid headings instead of a playbook."""
    body = text(name)
    if body is None:
        raise KeyError(name)
    lines = body.splitlines()
    heads = _headings(body)
    if section:
        want = _norm(section)
        cands = [h for h in heads if h[0] <= 3]
        hits = [h for h in cands if _norm(h[1]) == want] or [h for h in cands if want and want in _norm(h[1])]
        if len(hits) != 1:
            why = "AMBIGUOUS SECTION" if hits else "UNKNOWN SECTION"
            return {"name": name, "error": f"{why} {section[:60]!r}: use one of the headings listed", "headings": _titles(hits or cands, 2400)}
        lvl, title, start = hits[0]
        end = next((i for (lv, _, i) in heads if i > start and lv <= lvl), len(lines))
        chunk, cut = _cut("\n".join(lines[start:end]) + "\n", MAX_CHARS)
        out: dict = {"name": name, "section": title, "playbook": chunk}
        if cut:  # a long `##` section: its `###` children can be loaded one by one
            out.update(truncated=True, headings=_titles([h for h in heads if start < h[2] < end and h[0] > lvl]))
        return _fit(out)
    chunk, cut = _cut(body, MAX_CHARS)
    out = {"name": name, "playbook": chunk}
    if cut:
        out.update(truncated=True, headings=_titles([h for h in heads if h[0] <= 3]),
                   hint="Long playbook. Call skill again with section set to one of these headings to read the rest.")
    return _fit(out)


# --- search ------------------------------------------------------------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "how", "do", "i", "is", "what", "with", "about"}


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if w not in _STOP and len(w) > 1}


def search(query: str, limit: int = 8) -> list[dict]:
    """Best matching playbooks for a topic, as {name, about, sections}. Scores name words most, then description, then headings."""
    q = _words(query)
    if not q:
        return []
    scored = []
    for n in names():
        nw, dw = _words(n.replace("-", " ")), _words(describe(n, 400))
        hw = _words(" ".join(sections(n)))
        score = sum(4 * (w in nw) + 2 * (w in dw) + (w in hw) + 2 * any(w != x and (w in x or x in w) and min(len(w), len(x)) >= 4 for x in nw) for w in q)
        if score:
            scored.append((-score, n))
    scored.sort()
    return [{"name": n, "about": describe(n), "sections": len(sections(n))} for _, n in scored[: max(1, min(limit, 15))]]
