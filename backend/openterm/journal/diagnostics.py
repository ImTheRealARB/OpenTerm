"""Behaviour diagnostics: five fixed rules over one currency's round trips. Deterministic, no model, no randomness.

Each finding says in plain words what the rule is, what it found and the numbers behind it, and lists the round trips that
triggered it (`trips`, at most 50, with `trip_ids` for all of them). A rule that cannot be judged says why (`insufficient`);
a rule that finds nothing says `clear`. A finding is a pattern in YOUR history, not advice and not a forecast.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import defaultdict
from datetime import datetime

MIN_TRIPS = 10
SHOW = 50

# thresholds, kept in one place and quoted in each finding's `rule`
OVERTRADE_FLOOR = 5  # a busy day has at least this many entries ...
OVERTRADE_MULT = 2.0  # ... and at least this many times the median day
REVENGE_WINDOW_S = 30 * 60
REVENGE_SIZE = 1.25
DISPOSITION_RATIO = 1.5
DISPOSITION_MIN = 5
CREEP_STREAK = 2
CREEP_SIZE = 1.5
CREEP_MIN_PRIOR = 5
HOURS_MIN = 20
CORE_SHARE = 0.10
RARE_SHARE = 0.05


def dur(s: float | None) -> str:
    if s is None:
        return "-"
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s / 60:.0f} min"
    if s < 172800:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} days"


def money(x: float, ccy: str) -> str:
    return f"{'-' if x < 0 else ''}{abs(x):,.2f} {ccy}"


def _brief(t: dict) -> dict:
    return {"id": t["id"], "symbol": t["symbol"], "side": t["side"], "qty": t["qty"], "entry_time": t["entry_time"],
            "exit_time": t["exit_time"], "pnl": t["pnl"]}


def _finding(fid: str, title: str, rule: str, status: str, severity: str, plain: str, evidence: dict | None = None,
             trips: list[dict] | None = None) -> dict:
    trips = trips or []
    seen: set[str] = set()
    uniq = [t for t in trips if not (t["id"] in seen or seen.add(t["id"]))]
    ids: list[int] = []
    for t in uniq:
        for i in [*t["open_ids"], t["close_id"]]:
            if i not in ids:
                ids.append(i)
    return {"id": fid, "title": title, "rule": rule, "status": status, "severity": severity, "plain": plain,
            "evidence": evidence or {}, "trip_ids": [t["id"] for t in uniq], "trips": [_brief(t) for t in uniq[:SHOW]],
            "fill_ids": ids[:400]}


def _insufficient(fid: str, title: str, rule: str, why: str) -> dict:
    return _finding(fid, title, rule, "insufficient", "none", f"NOT ENOUGH HISTORY TO JUDGE: {why}")


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def _day(t: dict) -> str:
    return t["entry_time"][:10]


# ---------------------------------------------------------------- 1 overtrading
def overtrading(trips: list[dict], ccy: str) -> dict:
    fid, title = "overtrading", "Overtrading days"
    rule = (f"A busy day is a day with at least {OVERTRADE_FLOOR} entries and at least {OVERTRADE_MULT:g} times the median day's entries. "
            "Needs 10 trading days.")
    by_day: dict[str, list[dict]] = defaultdict(list)
    for t in trips:
        by_day[_day(t)].append(t)
    if len(by_day) < MIN_TRIPS:
        return _insufficient(fid, title, rule, f"{len(by_day)} trading days, need {MIN_TRIPS}")
    med = statistics.median(len(v) for v in by_day.values())
    limit = max(OVERTRADE_FLOOR, math.ceil(OVERTRADE_MULT * med))
    busy = sorted(d for d, v in by_day.items() if len(v) >= limit)
    if not busy:
        return _finding(fid, title, rule, "clear", "none",
                        f"No day reached {limit} entries (your median day has {med:g}). Your busiest day had {max(len(v) for v in by_day.values())}.")
    hit = [t for d in busy for t in by_day[d]]
    rest = [t for d, v in by_day.items() if d not in set(busy) for t in v]
    a, b = _mean([t["pnl"] for t in hit]), _mean([t["pnl"] for t in rest])
    worse = a is not None and b is not None and a < b
    plain = (f"On {len(busy)} day{'s' if len(busy) != 1 else ''} you made {limit} or more entries (a normal day for you is {med:g}). "
             f"Those days averaged {money(a, ccy)} per trade, other days {money(b, ccy) if b is not None else '-'}. "
             + ("Busy days did worse than normal days." if worse else "Busy days did not do worse than normal days."))
    days = [{"day": d, "entries": len(by_day[d]), "pnl": sum(t["pnl"] for t in by_day[d])} for d in busy]
    return _finding(fid, title, rule, "flagged", "high" if worse else "watch", plain,
                    {"median_entries": med, "threshold": limit, "days": days[:30], "avg_pnl_busy": a, "avg_pnl_other": b}, hit)


# ---------------------------------------------------------------- 2 revenge trades
def revenge(trips: list[dict], ccy: str) -> dict:
    fid, title = "revenge", "Revenge trades"
    rule = (f"A losing trade closes, then within {REVENGE_WINDOW_S // 60} minutes you open a new trade at least {REVENGE_SIZE:g} times as big "
            "(price x quantity). Needs 10 round trips.")
    if len(trips) < MIN_TRIPS:
        return _insufficient(fid, title, rule, f"{len(trips)} round trips, need {MIN_TRIPS}")
    by_entry = sorted(trips, key=lambda t: (t["entry_ts"], t["close_id"]))
    entries = [t["entry_ts"] for t in by_entry]
    pairs: list[tuple[dict, dict]] = []
    for loss in (t for t in trips if t["pnl"] < 0):
        i = bisect.bisect_right(entries, loss["exit_ts"])
        if i < len(by_entry) and by_entry[i]["entry_ts"] - loss["exit_ts"] <= REVENGE_WINDOW_S:
            nxt = by_entry[i]
            if nxt["id"] != loss["id"] and nxt["notional"] >= REVENGE_SIZE * loss["notional"]:
                pairs.append((loss, nxt))
    losses = sum(1 for t in trips if t["pnl"] < 0)
    if not pairs:
        return _finding(fid, title, rule, "clear", "none", f"None of your {losses} losing trades was followed by a bigger trade within {REVENGE_WINDOW_S // 60} minutes.")
    re_entries = [p[1] for p in pairs]
    rev_pnl = sum(t["pnl"] for t in re_entries)
    plain = (f"{len(pairs)} of your {losses} losing trades were followed within {REVENGE_WINDOW_S // 60} minutes by a trade at least "
             f"{REVENGE_SIZE:g} times as big. Those bigger trades made {money(rev_pnl, ccy)} in total.")
    ev = {"events": len(pairs), "losses": losses, "pnl_of_reentries": rev_pnl,
          "pairs": [{"loss": a["id"], "reentry": b["id"], "size_ratio": b["notional"] / a["notional"],
                     "gap_s": b["entry_ts"] - a["exit_ts"]} for a, b in pairs[:30]]}
    flat = [t for p in pairs for t in p]
    return _finding(fid, title, rule, "flagged", "high" if rev_pnl < 0 and len(pairs) >= 3 else "watch", plain, ev, flat)


# ---------------------------------------------------------------- 3 disposition effect
def disposition(trips: list[dict], ccy: str) -> dict:
    fid, title = "disposition", "Cutting winners early, letting losers run"
    rule = (f"Your losing trades are held at least {DISPOSITION_RATIO:g} times as long as your winning ones, on average. "
            f"Needs {DISPOSITION_MIN} winners and {DISPOSITION_MIN} losers.")
    wins = [t for t in trips if t["pnl"] > 0]
    loss = [t for t in trips if t["pnl"] < 0]
    if len(wins) < DISPOSITION_MIN or len(loss) < DISPOSITION_MIN:
        return _insufficient(fid, title, rule, f"{len(wins)} winners and {len(loss)} losers, need {DISPOSITION_MIN} of each")
    hw, hl = statistics.fmean(t["hold_s"] for t in wins), statistics.fmean(t["hold_s"] for t in loss)
    aw, al = statistics.fmean(t["pnl"] for t in wins), statistics.fmean(t["pnl"] for t in loss)
    ev = {"avg_hold_win_s": hw, "avg_hold_loss_s": hl, "avg_win": aw, "avg_loss": al, "ratio": (hl / hw) if hw > 0 else None}
    if hw <= 0:
        return _insufficient(fid, title, rule, "your winners have no holding time (all opened and closed in the same second)")
    ratio = hl / hw
    if ratio < DISPOSITION_RATIO:
        return _finding(fid, title, rule, "clear", "none",
                        f"Losers were held {dur(hl)} and winners {dur(hw)} on average (ratio {ratio:.2f}, flagged from {DISPOSITION_RATIO:g}).", ev)
    longest = sorted((t for t in loss if t["hold_s"] >= DISPOSITION_RATIO * hw), key=lambda t: -t["hold_s"])
    bigger = abs(al) > aw
    plain = (f"Losing trades were held {dur(hl)} on average, winning trades {dur(hw)}: {ratio:.1f} times longer. "
             f"Your average loss is {money(al, ccy)} and your average win {money(aw, ccy)}"
             + (", so the losers you hold are also bigger than the winners you take." if bigger else "."))
    return _finding(fid, title, rule, "flagged", "high" if ratio >= 2 and bigger else "watch", plain, ev, longest)


# ---------------------------------------------------------------- 4 size creep after wins
def size_creep(trips: list[dict], ccy: str) -> dict:
    fid, title = "creep", "Size creep after wins"
    rule = (f"After {CREEP_STREAK} winning trades in a row you open a trade at least {CREEP_SIZE:g} times your median size so far "
            f"(price x quantity). Needs 10 round trips and {CREEP_MIN_PRIOR} earlier trades for the median.")
    if len(trips) < MIN_TRIPS:
        return _insufficient(fid, title, rule, f"{len(trips)} round trips, need {MIN_TRIPS}")
    by_exit = sorted(trips, key=lambda t: (t["exit_ts"], t["close_id"]))
    exits = [t["exit_ts"] for t in by_exit]
    streak: list[int] = []
    run = 0
    for t in by_exit:
        run = run + 1 if t["pnl"] > 0 else 0
        streak.append(run)
    seen: list[float] = []
    events: list[dict] = []
    after = 0
    for t in sorted(trips, key=lambda t: (t["entry_ts"], t["close_id"])):
        if len(seen) >= CREEP_MIN_PRIOR:
            k = bisect.bisect_left(exits, t["entry_ts"])  # trades that closed before this entry
            if k and streak[k - 1] >= CREEP_STREAK:
                after += 1
                med = seen[len(seen) // 2] if len(seen) % 2 else (seen[len(seen) // 2 - 1] + seen[len(seen) // 2]) / 2
                if med > 0 and t["notional"] >= CREEP_SIZE * med:
                    events.append(t)
        bisect.insort(seen, t["notional"])
    if not events:
        return _finding(fid, title, rule, "clear", "none", f"{after} trades followed {CREEP_STREAK}+ wins and none was unusually big.")
    pnl = sum(t["pnl"] for t in events)
    ids = {t["id"] for t in events}
    other = _mean([t["pnl"] for t in trips if t["id"] not in ids])
    share = len(events) / after if after else 0.0
    plain = (f"{len(events)} of the {after} trades that followed {CREEP_STREAK} or more wins in a row were at least {CREEP_SIZE:g} times "
             f"your usual size. They made {money(pnl, ccy)} in total ({money(pnl / len(events), ccy)} each, other trades {money(other, ccy) if other is not None else '-'}).")
    flagged = len(events) >= 3 and share >= 0.25
    return _finding(fid, title, rule, "flagged" if flagged else "clear", ("high" if pnl < 0 else "watch") if flagged else "none",
                    plain if flagged else f"{len(events)} oversized trades after wins, too few to call a pattern (flagged from 3 and 25% of trades after a win streak). " + plain,
                    {"events": len(events), "after_streak": after, "share": share, "pnl": pnl, "avg_pnl_other": other}, events if flagged else [])


# ---------------------------------------------------------------- 5 outside usual hours
def off_hours(trips: list[dict], ccy: str) -> dict:
    fid, title = "hours", "Trading outside your usual hours"
    rule = (f"Your usual window runs from your first to your last hour that holds at least {CORE_SHARE:.0%} of your entries. "
            f"An entry at least one hour outside it, in an hour holding under {RARE_SHARE:.0%} of entries, is off-hours. Needs {HOURS_MIN} round trips.")
    if len(trips) < HOURS_MIN:
        return _insufficient(fid, title, rule, f"{len(trips)} round trips, need {HOURS_MIN}")
    hours = [datetime.fromisoformat(t["entry_time"]).hour for t in trips]
    n = len(hours)
    share = {h: hours.count(h) / n for h in set(hours)}
    core = [h for h, s in share.items() if s >= CORE_SHARE]
    if not core:
        return _finding(fid, title, rule, "clear", "none", "Your entries are spread over many hours, so there is no single usual window to leave.")
    lo, hi = min(core), max(core)
    odd = [t for t, h in zip(trips, hours, strict=True) if (h < lo or h > hi) and share[h] < RARE_SHARE]
    window = f"{lo:02d}:00-{hi:02d}:59"
    if len(odd) < 3:
        return _finding(fid, title, rule, "clear", "none", f"Your usual window is {window}; only {len(odd)} entries were clearly outside it.")
    ids = {t["id"] for t in odd}
    a, b = _mean([t["pnl"] for t in odd]), _mean([t["pnl"] for t in trips if t["id"] not in ids])
    worse = a is not None and b is not None and a < b
    plain = (f"Most of your entries are between {window}. {len(odd)} entries were outside it and averaged {money(a, ccy)}, "
             f"against {money(b, ccy) if b is not None else '-'} for the rest. " + ("Off-hours entries did worse." if worse else "Off-hours entries did not do worse."))
    return _finding(fid, title, rule, "flagged", "high" if worse and len(odd) >= 5 else "watch", plain,
                    {"window": window, "entries_outside": len(odd), "avg_pnl_outside": a, "avg_pnl_rest": b}, odd)


def diagnose(trips: list[dict], currency: str) -> list[dict]:
    """The five findings for one currency's round trips."""
    return [overtrading(trips, currency), revenge(trips, currency), disposition(trips, currency), size_creep(trips, currency),
            off_hours(trips, currency)]
