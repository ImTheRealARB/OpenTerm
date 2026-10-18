"""docs/FUNCTIONS.md is generated from the function registry and keybindings; it must not go stale."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_functions_doc.py"


def test_functions_doc_is_current():
    spec = importlib.util.spec_from_file_location("gen_functions_doc", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.is_current(), "docs/FUNCTIONS.md is out of date: run `python scripts/gen_functions_doc.py` and commit it"
