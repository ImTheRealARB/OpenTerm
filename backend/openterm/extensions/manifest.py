"""Extension manifests (`extension.yaml`) and the rules for names.

name: lowercase letters, digits, `_` and `-`, starting with a letter, at most 32 characters. It becomes `/api/ext/<name>/...`, the
`ext.<name>.` tool prefix and the `EXT <name>` command, so nothing else is allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}\Z")
SHORT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}\Z")  # a tool or route name inside an extension
ADDS = ("provider", "tools", "route")
LIMIT = 200


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    author: str
    license: str
    description: str = ""
    adds: tuple[str, ...] = field(default_factory=tuple)
    entry: str = "extension.py"


def _str(raw: dict, key: str, required: bool = True) -> str:
    v = raw.get(key)
    if v is None or v == "":
        if required:
            raise ManifestError(f"MANIFEST NEEDS {key}")
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise ManifestError(f"MANIFEST {key} MUST BE TEXT")
    return str(v)[:LIMIT]


def parse_manifest(raw: object, expect_name: str | None = None) -> Manifest:
    if not isinstance(raw, dict):
        raise ManifestError("MANIFEST MUST BE A YAML MAPPING")
    name = _str(raw, "name")
    if not NAME_RE.match(name):
        raise ManifestError("MANIFEST name MUST BE LOWERCASE LETTERS, DIGITS, _ AND -, STARTING WITH A LETTER (MAX 32)")
    if expect_name is not None and name != expect_name:
        raise ManifestError(f"MANIFEST name {name} DOES NOT MATCH ITS FOLDER {expect_name}")
    adds = raw.get("adds") or []
    if not isinstance(adds, list) or any(a not in ADDS for a in adds):
        raise ManifestError(f"MANIFEST adds MUST BE A LIST OF {', '.join(ADDS)}")
    entry = _str(raw, "entry", required=False) or "extension.py"
    if "/" in entry or "\\" in entry or ".." in entry or not entry.endswith(".py"):
        raise ManifestError("MANIFEST entry MUST BE A .py FILE IN THE EXTENSION FOLDER")
    return Manifest(name=name, version=_str(raw, "version"), author=_str(raw, "author"), license=_str(raw, "license"),
                    description=_str(raw, "description", required=False), adds=tuple(adds), entry=entry)
