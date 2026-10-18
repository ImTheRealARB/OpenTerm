"""Expiry selection and (step 5) the implied-vol surface fit. Pure: no I/O, no clock."""

from __future__ import annotations

#: Days after the nearest expiry that the other seven expiries are chosen closest to (spec decision H).
EXPIRY_OFFSETS_DAYS = (7, 30, 60, 90, 180, 270, 365)


def pick_expiries(dates: list[int]) -> list[int]:
    """The eight expiries every options function uses: the nearest, then the one closest to +7, +30, +60, +90, +180, +270 and +365
    days after it, each used once. Shared by PCR, OVDV, SKEW and HIVG so one set of chain fetches serves all four. The recorder
    (scripts/record_phase14.py) has the same rule; a test locks the two together."""
    if not dates:
        return []
    ordered = sorted(dates)
    first, picked = ordered[0], [ordered[0]]
    for days in EXPIRY_OFFSETS_DAYS:
        rest = [d for d in ordered if d not in picked]
        if rest:
            picked.append(min(rest, key=lambda d: abs(d - (first + days * 86400))))
    return sorted(picked)
