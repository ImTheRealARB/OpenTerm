"""AISstream (aisstream.io, free key, BETA WebSocket): live ship positions inside a bounding box. Capability `ais`.

This is not a quote or history source. It answers one question, "which ships reported a position in this box in the last few
seconds?", by opening the socket, sending one subscription, reading for a hard-capped time and number of messages, and closing.
Nothing here keeps a long-lived connection, so the server never imports or runs this code at startup (`websockets` is imported
inside the functions that connect).

Facts that shape the code (all from aisstream.io/documentation, read 2026-11-05):
  - Three subscribed connections per account and three open connections per IP: listens run ONE AT A TIME (a lock), so a burst of panels
    can never hit the limit.
  - The subscription must arrive within 3 seconds of connecting: it is sent as soon as the socket opens.
  - The service has NO uptime promise and does not replay messages. A listen is a sample of the last few seconds, never a full picture.
  - Direct browser connections are not allowed: the key stays here, in the server. It is sent in the first message, never in a URL,
    and never put in an error text (a failed connect reports only the exception class name).
  - ShipStaticData (destination, ETA, size) is sent per ship only every few minutes, so one short listen sees it for few ships. A small
    memory of the last static record per MMSI lets repeated listens fill destinations in (each record keeps its own time).

With no key `supports()` stays true and the call raises `key_required` BEFORE any connection: AIS shows
`KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS`. In fixture mode a key (any text) replays tests/fixtures/ais_stream_docshape.json,
which is DOC-SHAPED (invented ships), and the source label says so.

NOT verified against the live service (no key existed): how a bad key is answered, what the real MetaData looks like beyond the docs,
and how much static data arrives in a few seconds. The wire code is tested against a local WebSocket server in the documented shape.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import orjson

from . import aisstream_parse as ap
from .base import Provider, ProviderError

CAPABILITY = "ais"
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ais_stream_docshape.json"
STATIC_KEEP = 4000  # remembered static records (about 1 MB)
STATIC_TTL_S = 6 * 3600.0
MAX_SECONDS = 15.0
MAX_MESSAGES = 5000
CONNECT_TIMEOUT_S = 8.0


def _closed(e: Exception) -> str:
    """A screen-ready line for a connection the service closed. Only the close code and reason: never anything that could hold the key."""
    rcvd = getattr(e, "rcvd", None)
    code = getattr(rcvd, "code", None)
    reason = (getattr(rcvd, "reason", "") or "")[:60]
    return f"AISSTREAM CLOSED THE CONNECTION{f' ({code} {reason})'.rstrip() if code else ''}: A REFUSED KEY, THE 3-CONNECTION LIMIT OR THE BETA SERVICE IS DOWN"


async def _open(url: str, key: str, box: tuple[float, float, float, float], types: tuple[str, ...]):
    """Connects and sends the subscription. Returns the open socket (caller closes it). Imports websockets here, not at module level."""
    import websockets

    try:
        # close_timeout: after we stop reading (cap reached) the client's queue is full, so the service's close frame is never read;
        # without a short limit `ws.close()` would wait the default 10 s for it.
        ws = await websockets.connect(url, open_timeout=CONNECT_TIMEOUT_S, max_size=1 << 20, ping_interval=20, close_timeout=1.0,
                                      compression="deflate")
    except (OSError, TimeoutError, websockets.WebSocketException) as e:
        raise ProviderError("unavailable", f"AISSTREAM UNREACHABLE: {type(e).__name__}") from e  # class name only, never str(e)
    try:
        await ws.send(orjson.dumps(ap.subscription(key, box, types)).decode())
    except websockets.WebSocketException as e:
        await ws.close()
        raise ProviderError("unavailable", _closed(e)) from e
    return ws


class AisStreamProvider(Provider):
    name = "aisstream"
    label = "AISstream (free key, beta WebSocket)"
    capabilities = frozenset({CAPABILITY})
    markets = "Live ship positions (AIS) inside a bounding box, plus destination and ETA as ships report them"
    terms = "Free key (AISSTREAM_API_KEY). BETA: no uptime promise, no replay, 3 connections per account and per IP. Positions are as reported by ships."
    key_name = "AISSTREAM_API_KEY"
    url = ap.URL  # tests point this at a local server

    def __init__(self, http: Any, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.source = "aisstream (DOC-SHAPED fixture, NOT A RECORDING)" if self.fixtures else "aisstream"
        self._key = ""
        self._lock = asyncio.Lock()  # one listen at a time: the account allows only 3 connections
        self._statics: OrderedDict[int, dict[str, Any]] = OrderedDict()

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def set_keys(self, values: dict[str, str] | None) -> None:
        self._key = (values or {}).get("AISSTREAM_API_KEY", "")

    async def ais_listen(self, box: tuple[float, float, float, float], seconds: float = 8.0, max_messages: int = 3000) -> dict[str, Any]:
        """Listens inside `box` for at most `seconds` or `max_messages` data messages, whichever comes first.

        Returns {"positions": {mmsi: newest position}, "statics": {mmsi: static record}, "received": n data messages, "capped": hit the message cap,
        "listened_s": how long we actually listened, "source"}. An empty `positions` is a real answer (quiet area or slow feed), not an error.
        """
        if not self._key:
            raise ProviderError("key_required", "AISSTREAM_API_KEY is not set")
        box = ap.check_box(*box)  # ValueError for a bad box, before any connection
        seconds, max_messages = min(max(seconds, 0.2), MAX_SECONDS), min(max(max_messages, 1), MAX_MESSAGES)
        async with self._lock:
            if self.fixtures:
                msgs, listened = self._fixture_messages(), 0.1
            else:
                msgs, listened = await self._read(box, seconds, max_messages)
            return self._assemble(msgs, listened, max_messages)

    # --- reading -----------------------------------------------------------------------------------------------------------
    def _fixture_messages(self) -> list[dict[str, Any]]:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))["messages"]

    async def _read(self, box: tuple[float, float, float, float], seconds: float, cap: int) -> tuple[list[dict[str, Any]], float]:
        import websockets

        started = time.monotonic()
        ws = await _open(self.url, self._key, box, ap.FILTER_TYPES)
        msgs: list[dict[str, Any]] = []
        confirmed = False
        try:
            while len(msgs) < cap:
                left = started + seconds - time.monotonic()
                if left <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), left)
                except TimeoutError:
                    break
                except websockets.ConnectionClosed as e:
                    if confirmed:
                        break  # the service hung up mid-listen: use what arrived
                    raise ProviderError("unavailable", _closed(e)) from e
                try:
                    msg = ap.decode(raw)
                except ValueError:
                    continue  # one unreadable frame is not worth failing the whole listen
                kind = ap.kind_of(msg)
                if kind == "error":
                    text = ap.error_text(msg)
                    # The service names the key in its complaint; keep the wording, drop the key if it was echoed.
                    text = text.replace(self._key, "***")
                    raise ProviderError("key_required" if "key" in text.lower() else "unavailable", f"AISSTREAM: {text}")
                if kind == "confirmation":
                    confirmed = True
                    continue
                confirmed = True  # data without a confirmation still proves the subscription was accepted
                msgs.append(msg)
        finally:
            await ws.close()
        return msgs, time.monotonic() - started

    # --- turning messages into the answer -----------------------------------------------------------------------------------
    def _assemble(self, msgs: list[dict[str, Any]], listened: float, cap: int) -> dict[str, Any]:
        now = time.time()
        positions: dict[int, dict[str, Any]] = {}
        for msg in msgs:
            kind = ap.kind_of(msg)
            if kind == "position" and (p := ap.position(msg, now)) is not None:
                old = positions.get(p["mmsi"])
                if old is None or p["seen"] >= old["seen"]:
                    positions[p["mmsi"]] = p
            elif kind == "static" and (s := ap.static(msg, now)) is not None:
                s["rx"] = now  # when WE got it: the memory's age is measured from here, whatever the message's own clock says
                self._statics[s["mmsi"]] = s
                self._statics.move_to_end(s["mmsi"])
        while len(self._statics) > STATIC_KEEP:
            self._statics.popitem(last=False)
        for mmsi in [m for m, s in self._statics.items() if now - s["rx"] > STATIC_TTL_S]:
            del self._statics[mmsi]
        return {
            "positions": positions,
            "statics": {m: self._statics[m] for m in positions if m in self._statics},
            "received": len(msgs),
            "capped": len(msgs) >= cap,
            "listened_s": round(listened, 2),
            "source": self.source,
        }


async def check_key(values: dict[str, str], url: str = ap.URL, wait_s: float = 8.0) -> tuple[str, str | None]:
    """APIKEYS key test: subscribe to one tiny mid-ocean box and one message type, and wait for the service's answer.

    OK = a subscription confirmation (or any data) arrived. INVALID = the service answered with an error that names the key.
    ERROR = anything else (closed without a word, no answer, unreachable). The cheapest check the docs allow; a closed connection is
    ambiguous (the docs list a refused key among several causes), so it is ERROR with the reason, not a guess at INVALID.
    """
    import websockets

    key = values["AISSTREAM_API_KEY"]
    box = (0.0, -30.0, 0.1, -29.9)  # open Atlantic: almost never any traffic, so almost no bytes
    try:
        ws = await _open(url, key, box, ("PositionReport",))
    except ProviderError as e:
        return "ERROR", str(e)
    try:
        raw = await asyncio.wait_for(ws.recv(), wait_s)
    except TimeoutError:
        return "ERROR", "NO ANSWER FROM AISSTREAM IN TIME (IT IS A BETA SERVICE)"
    except websockets.ConnectionClosed as e:
        return "ERROR", _closed(e)
    finally:
        await ws.close()
    try:
        msg = ap.decode(raw)
    except ValueError:
        return "ERROR", "AISSTREAM SENT SOMETHING UNREADABLE"
    if ap.kind_of(msg) == "error":
        text = ap.error_text(msg).replace(key, "***")
        return ("INVALID" if "key" in text.lower() else "ERROR"), f"AISSTREAM: {text}"
    return "OK", None
