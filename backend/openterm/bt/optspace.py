"""BT OPT parameter space (Phase 26 items 1-2): `{lo..hi:step}` ranges inside a rule or strategy code, and the three ways
of choosing which parameter sets to run (every combination, a random sample, a genetic search).

Pure Python on purpose: the server parses and counts a template before it submits the job (no pandas there), and the
`bt.opt` job (worker side) uses the very same functions, so the two can never disagree about the space.

Vocabulary used below:
- a *template* is the rule or code text with one or more ranges in braces, e.g. `SMA{10..50:5}>SMA{50..200:25}`;
- a *parameter* is one range (named P1, P2, ... in order of appearance) and its list of values;
- an *index tuple* picks one value per parameter by position, e.g. (0, 3) = the first P1 value and the fourth P2 value.
  Searching over positions (not raw numbers) keeps the genetic operators simple and every value exact.
"""

from __future__ import annotations

import itertools
import math
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# `{lo..hi}` or `{lo..hi:step}`; numbers may be negative or decimal. Spaces inside the braces are allowed.
RANGE_RE = re.compile(r"\{\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)\s*(?::\s*(\d+(?:\.\d+)?))?\s*\}")
# Anything that LOOKS like a range attempt (braces around two dots) but did not match RANGE_RE is a typo we must report,
# never pass through: in Python code `{...}` is legal syntax, so a broken range would otherwise run as something else.
ATTEMPT_RE = re.compile(r"\{[^{}\n]*\.\.[^{}\n]*\}")

GRID_CAP = 2000  # most runs one optimisation may make (spec item 1)
MAX_PARAMS = 6
MAX_VALUES = 500  # values in one range
METHODS = ("GRID", "RANDOM", "GA")


class SpaceError(ValueError):
    """The template or search settings are unusable; the message is shown to the user as is."""


@dataclass(frozen=True)
class Param:
    name: str  # P1, P2, ...
    values: tuple[str, ...]  # canonical text of each value ("10", "0.5"), in increasing order
    where: str  # the text just before the range (for labels such as "SMA"), at most 12 characters


def _dec(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation:  # RANGE_RE only lets numbers through, so this would be a bug: say so
        raise SpaceError(f"BAD NUMBER {text!r} IN A RANGE") from None


def _canon(d: Decimal) -> str:
    """`Decimal('10.0')` -> "10", `Decimal('0.50')` -> "0.5": the text pasted into the rule or code."""
    s = format(d.normalize(), "f")
    return s if s not in ("-0", "") else "0"


def parse(text: str) -> tuple[list[str], list[Param]]:
    """Template -> (literal parts, parameters). `parts` has one more item than `params`: the text is
    parts[0] + value(P1) + parts[1] + value(P2) + ... + parts[-1]."""
    parts: list[str] = []
    params: list[Param] = []
    pos = 0
    for m in RANGE_RE.finditer(text):
        lo, hi = _dec(m.group(1)), _dec(m.group(2))
        step = _dec(m.group(3)) if m.group(3) else Decimal(1)
        label = f"{{{m.group(1)}..{m.group(2)}{':' + m.group(3) if m.group(3) else ''}}}"
        if step <= 0:
            raise SpaceError(f"{label}: THE STEP MUST BE ABOVE 0")
        if lo > hi:
            raise SpaceError(f"{label}: THE FIRST NUMBER MUST NOT BE ABOVE THE SECOND")
        count = int((hi - lo) / step) + 1
        if count > MAX_VALUES:
            raise SpaceError(f"{label}: {count} VALUES, AT MOST {MAX_VALUES} PER RANGE")
        values = tuple(_canon(lo + step * i) for i in range(count))
        before = text[pos:m.start()]
        parts.append(before)
        params.append(Param(f"P{len(params) + 1}", values, re.sub(r"\s+", " ", before[-12:]).strip(" =:")))
        pos = m.end()
    parts.append(text[pos:])
    leftover = ATTEMPT_RE.search("".join(parts))
    if leftover:
        raise SpaceError(f"BAD RANGE {leftover.group(0)}: WRITE {{LO..HI}} OR {{LO..HI:STEP}}, E.G. {{10..50:5}}")
    if not params:
        raise SpaceError("BT OPT NEEDS AT LEAST ONE RANGE IN BRACES, E.G. SMA{10..50:5}>SMA{50..200:25}")
    if len(params) > MAX_PARAMS:
        raise SpaceError(f"{len(params)} RANGES, AT MOST {MAX_PARAMS}")
    return parts, params


NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,39}$")


def code_template(code: str, ranges: dict[str, str]) -> str:
    """A saved Python strategy stays valid Python, so its ranges come from the command instead: `FAST={10..50:5}` replaces
    the number in the strategy's line `FAST = 20` (a module-level constant, optionally typed `FAST: int = 20`, optionally
    followed by a comment). Exactly one such line must exist per name."""
    for name, rng in ranges.items():
        if not NAME_RE.match(name):
            raise SpaceError(f"{name[:40]}: A PARAMETER NAME IS UPPERCASE LETTERS, DIGITS AND _ (E.G. FAST)")
        if not RANGE_RE.fullmatch(rng.strip()):
            raise SpaceError(f"{name}={rng[:40]}: WRITE {name}={{LO..HI}} OR {name}={{LO..HI:STEP}}")
        pat = re.compile(rf"^({re.escape(name)}\s*(?::\s*\w+\s*)?=\s*)(-?\d+(?:\.\d+)?)(?=\s*(?:#.*)?$)", re.MULTILINE)
        hits = list(pat.finditer(code))
        if len(hits) != 1:
            raise SpaceError(f"THE STRATEGY NEEDS EXACTLY ONE LINE `{name} = <number>` AT THE START OF A LINE (FOUND {len(hits)})")
        m = hits[0]
        code = code[:m.start(2)] + rng.strip() + code[m.end(2):]
    return code


def render(parts: list[str], params: list[Param], idx: tuple[int, ...]) -> str:
    """The concrete rule or code for one index tuple."""
    out = [parts[0]]
    for p, i, tail in zip(params, idx, parts[1:], strict=True):
        out.append(p.values[i])
        out.append(tail)
    return "".join(out)


def shown(parts: list[str], params: list[Param]) -> str:
    """The template with P1, P2, ... in place of the ranges (a short label for the results header)."""
    out = [parts[0]]
    for p, tail in zip(params, parts[1:], strict=True):
        out.append(f"{{{p.name}}}")
        out.append(tail)
    return "".join(out)


def count(params: list[Param]) -> int:
    return math.prod(len(p.values) for p in params)


def decode(flat: int, params: list[Param]) -> tuple[int, ...]:
    """Flat position in the full grid (row-major, last parameter fastest, like itertools.product) -> index tuple."""
    out = []
    for p in reversed(params):
        flat, r = divmod(flat, len(p.values))
        out.append(r)
    return tuple(reversed(out))


def grid(params: list[Param]) -> list[tuple[int, ...]]:
    n = count(params)
    if n > GRID_CAP:
        raise SpaceError(f"THE GRID HAS {n:,} RUNS, AT MOST {GRID_CAP:,}: USE METHOD=RANDOM N=... OR METHOD=GA, OR WIDER STEPS")
    return list(itertools.product(*(range(len(p.values)) for p in params)))


def random_sample(params: list[Param], n: int, seed: int) -> list[tuple[int, ...]]:
    """`n` different parameter sets drawn without replacement (all of them when the space is smaller). Same seed, same sets."""
    total = count(params)
    rng = random.Random(seed)
    # random.sample over a range object does not build the range: fine even for a space of billions.
    return [decode(f, params) for f in rng.sample(range(total), min(n, total))]


def search_size(method: str, params: list[Param], n: int, pop: int, gen: int) -> int:
    """Upper bound on the backtests a search makes (the GA re-uses a cached score for a repeated parameter set)."""
    if method == "GRID":
        return len(grid(params))  # raises past the cap
    if method == "RANDOM":
        return min(n, count(params))
    return min(pop * gen, count(params))


def _key(score: float) -> float:
    """Ranking key: a missing or NaN score (a failed or empty run) ranks below every real one."""
    return score if isinstance(score, int | float) and not math.isnan(score) else -math.inf


def genetic(params: list[Param], score: Callable[[tuple[int, ...]], float], pop: int, gen: int, seed: int,
            on_generation: Callable[[int], None] | None = None) -> dict[tuple[int, ...], float]:
    """A small genetic search over index tuples, fully determined by `seed`.

    Each generation: score everyone (a parameter set seen before re-uses its cached score, so it costs no backtest), keep
    the 2 best unchanged (elitism), and fill the rest with children: two parents picked by 3-way tournaments, each gene taken
    from either parent with even odds (uniform crossover), then each gene re-drawn at random with probability
    max(0.1, 1 / number of parameters) (mutation). Returns every scored parameter set with its score, in scoring order.
    """
    rng = random.Random(seed)
    sizes = [len(p.values) for p in params]
    total = count(params)
    cache: dict[tuple[int, ...], float] = {}

    def fit(ind: tuple[int, ...]) -> float:
        if ind not in cache:
            cache[ind] = score(ind)
        return cache[ind]

    def rand_ind() -> tuple[int, ...]:
        return tuple(rng.randrange(s) for s in sizes)

    def tournament(pool: list[tuple[int, ...]]) -> tuple[int, ...]:
        """The best of 3 individuals drawn at random: good ones are picked more often, weak ones still sometimes."""
        return max(rng.sample(pool, min(3, len(pool))), key=lambda i: _key(cache[i]))

    # Start from distinct individuals where the space allows it (a tiny space simply holds fewer).
    population: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    while len(population) < pop and len(seen) < total:
        ind = rand_ind()
        if ind not in seen:
            seen.add(ind)
            population.append(ind)
    mutate_p = max(0.1, 1 / len(sizes))
    for g in range(gen):
        for ind in population:
            fit(ind)
        if on_generation:
            on_generation(g)
        if g == gen - 1:
            break
        ranked = sorted(population, key=lambda i: _key(cache[i]), reverse=True)
        children = ranked[:2]
        while len(children) < len(population):
            a, b = tournament(population), tournament(population)
            child = [a[j] if rng.random() < 0.5 else b[j] for j in range(len(sizes))]
            for j, s in enumerate(sizes):
                if rng.random() < mutate_p:
                    child[j] = rng.randrange(s)
            children.append(tuple(child))
        population = children
    return cache


def neighbours(idx: tuple[int, ...], params: list[Param]) -> list[tuple[int, ...]]:
    """Parameter sets one step away in exactly one parameter (the "best region" around a winner)."""
    out = []
    for j, p in enumerate(params):
        for d in (-1, 1):
            k = idx[j] + d
            if 0 <= k < len(p.values):
                out.append(idx[:j] + (k,) + idx[j + 1:])
    return out


def on_edge(idx: tuple[int, ...], params: list[Param]) -> list[str]:
    """Names of the parameters whose chosen value is the first or last of its range (ranges of 3+ values only: with 1 or 2
    values every choice is an end, which says nothing)."""
    return [p.name for p, i in zip(params, idx, strict=True) if len(p.values) >= 3 and i in (0, len(p.values) - 1)]
