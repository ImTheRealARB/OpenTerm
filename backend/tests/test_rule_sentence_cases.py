"""The rule strings behind the BT plain-English builder (frontend/src/functions/ruleSentence.cases.json) must mean the
same to the backend parser: every valid case parses, every canonical form parses, every invalid one is rejected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openterm.bt import rules

CASES = json.loads((Path(__file__).resolve().parents[2] / "frontend/src/functions/ruleSentence.cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["rule"])
def test_valid_rule_and_canonical_form_parse(case):
    assert _norm(rules.parse(case["canon"])) == _norm(rules.parse(case["rule"]))


@pytest.mark.parametrize("rule", CASES["invalid"])
def test_invalid_rule_is_rejected(rule):
    with pytest.raises(rules.RuleError):
        rules.parse(rule)


def _norm(node):
    """Compare structure only: terms carry their source column, which differs between spellings."""
    if isinstance(node, rules.BoolOp):
        return rules.BoolOp(node.op, tuple(_norm(x) for x in node.items))
    return rules.Cmp(_t(node.left), node.op, _t(node.right))


def _t(t):
    return rules.Term(t.kind, t.n, 0, t.name)
