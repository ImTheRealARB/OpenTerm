"""Review sprint, area backend-api: one test per bug found. Each is named after the bug."""

import io
import logging
import random

import pytest

from openterm import redact
from openterm.portfolio import check_currency
from openterm.userdata import UserDataError
from openterm.world.tickbuf import TickRing, bucket

SECRET = "sk-review-0123456789abcdef"


# --- redact: tracebacks and uvicorn handlers --------------------------------------------------------------------------
def _logger_with_stream(name: str) -> tuple[logging.Logger, io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger(name)
    log.addHandler(handler)
    log.propagate = False
    return log, stream, handler


def test_redact_filter_masks_secret_inside_a_logged_traceback():
    """A secret in an exception message (an httpx error carries the full URL) used to reach stderr in the traceback."""
    redact.register([SECRET])
    log, stream, handler = _logger_with_stream("review.tb")
    handler.addFilter(redact._FILTER)
    try:
        try:
            raise RuntimeError(f"GET https://example.test/x?foo=1 failed with {SECRET}")
        except RuntimeError:
            log.exception("request failed")
        out = stream.getvalue()
        assert "request failed" in out and "RuntimeError" in out
        assert SECRET not in out
    finally:
        log.removeHandler(handler)
        redact.unregister([SECRET])


def test_redact_install_filters_the_uvicorn_handlers():
    """uvicorn's own loggers do not propagate to root, so their handlers (access line, ASGI exception traceback) were unfiltered."""
    log, _, handler = _logger_with_stream("uvicorn.error")
    try:
        redact.install()
        assert redact._FILTER in handler.filters
    finally:
        log.removeHandler(handler)
        log.propagate = True


def test_redact_masks_telegram_bot_token_shape_and_key_headers_even_when_unregistered():
    token = "123456789:AAEhBP0av18Fg3fP9iD5kQ2xLmN7oR6sTuV"
    assert token not in redact.redact(f"GET https://api.telegram.org/bot{token}/getMe")
    assert "k3y-value-abcdef" not in redact.redact("headers: x-api-key: k3y-value-abcdef")
    assert "k3y-value-abcdef" not in redact.redact("APCA-API-SECRET-KEY=k3y-value-abcdef")
    assert redact.redact("GET /api/quote?symbols=AAPL") == "GET /api/quote?symbols=AAPL"


def test_key_error_body_is_redacted(client):
    from openterm.api import key_error

    body = key_error("bad_request", f"BAD {SECRET}").body.decode()
    assert "sk-review" not in body  # masked by the generic sk- shape even when unregistered


# --- the "$ lets a trailing newline through" family --------------------------------------------------------------------
def test_check_currency_refuses_a_trailing_newline():
    with pytest.raises(UserDataError):
        check_currency("USD\n")
    assert check_currency("usd") == "USD"
    assert check_currency("GBp") == "GBp"


def test_settings_zone_chord_and_model_refuse_a_trailing_newline():
    from openterm import settings_store as ss

    for field, bad in (("clocks", ["UTC\n"]), ("keys", {"openHelp": ["Ctrl+K\n"]}), ("ai", {"model": "vendor/name\n"})):
        with pytest.raises(UserDataError):
            ss.validate({field: bad})
    assert ss.validate({"clocks": ["UTC", "America/New_York"], "keys": {"openHelp": ["Ctrl+K"]},
                        "ai": {"model": "vendor/name"}})["clocks"] == ["UTC", "America/New_York"]


# --- request bodies and symbols are bounded ----------------------------------------------------------------------------
def test_json_body_over_the_cap_is_refused_without_parsing(client):
    big = b" " * (5 * 1024 * 1024)
    r = client.put("/api/watchlists/BIG", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["kind"] == "too_large"


def test_history_profile_and_resolve_refuse_an_unbounded_symbol(client):
    long = "A" * 200
    assert client.get("/api/history", params={"symbol": long}).status_code == 422
    assert client.get("/api/profile", params={"symbol": long}).status_code == 422
    assert client.get("/api/resolve", params={"symbol": long}).status_code == 422
    assert client.get("/api/resolve", params={"symbol": "btcusd"}).json()["symbol"] == "BTC-USD"


# --- GIP bucket: the faster loop must give the same bars -------------------------------------------------------------
def _reference_bucket(t_ms, price, cum_vol, bar_s):
    """The pre-review implementation, kept as the oracle."""
    import math

    n = len(t_ms)
    order = range(n) if all(t_ms[i] <= t_ms[i + 1] for i in range(n - 1)) else sorted(range(n), key=t_ms.__getitem__)
    out: dict = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    have_vol, base, cur = False, None, None
    for i in order:
        b = (t_ms[i] // 1000 // bar_s) * bar_s
        px, vi, delta = price[i], cum_vol[i], 0.0
        if not math.isnan(vi):
            have_vol = True
            if base is not None and vi >= base:
                delta = vi - base
            base = vi
        if cur != b:
            cur = b
            for k in "ohlc":
                out[k].append(px)
            out["t"].append(b)
            out["v"].append(delta)
        else:
            out["h"][-1] = max(out["h"][-1], px)
            out["l"][-1] = min(out["l"][-1], px)
            out["c"][-1] = px
            out["v"][-1] += delta
    if not have_vol:
        out["v"] = None
    return out


@pytest.mark.parametrize("bar_s", [1, 5, 15, 60])
def test_bucket_matches_the_reference_on_ordered_unordered_and_volumeless_ticks(bar_s):
    rng = random.Random(7)
    ring, ms = TickRing(), 1_700_000_000_000
    for i in range(3000):
        ms += rng.randint(0, 900)
        vol = None if i % 7 == 0 else float(i if i % 500 else 0)  # gaps and a day roll (cumulative volume falls)
        ring.add(ms, 100 + rng.random(), vol, "y")
    t, p, v = ring.view()
    assert bucket(t, p, v, bar_s) == _reference_bucket(t, p, v, bar_s)
    idx = list(range(len(t)))
    rng.shuffle(idx)
    ts, ps, vs = [t[i] for i in idx], [p[i] for i in idx], [v[i] for i in idx]
    assert bucket(ts, ps, vs, bar_s) == _reference_bucket(ts, ps, vs, bar_s)
    nan = float("nan")
    assert bucket(t, p, [nan] * len(t), bar_s) == _reference_bucket(t, p, [nan] * len(t), bar_s)
    assert bucket([], [], [], bar_s)["t"] == []
