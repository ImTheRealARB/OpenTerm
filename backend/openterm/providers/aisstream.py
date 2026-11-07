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
  - The feed is sparse, so the LAST POSITION per MMSI is remembered for 5 minutes (`PositionMemory`). Each listen answers with its own ships
    plus remembered ones still inside the box; every ship says whether it is remembered, and none older than 5 minutes is ever returned.

With no key `supports()` stays true and the call raises `key_required` BEFORE any connection: AIS shows
`KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS`. In fixture mode a key (any text) replays tests/fixtures/ais_stream_recording.json, a REAL
recording made on 2026-11-05 (only the messages inside the box asked for, like the live service), and the source label says it is a replay.

Checked live on 2026-11-05 with a real key (see aisstream_parse.py for the message shapes):
  - The subscription, the [lat, lon] corner order and the message shapes are right. The FEED IS SPARSE: about 80 messages a second for the whole
    world. A 15-30 s listen saw 2-3 ships in the Singapore Strait, 2 at Dover, 2 at Gibraltar and NOTHING at Suez, Hormuz, Bab el-Mandeb,
    Bosphorus or Panama. That is receiver coverage (the free feed comes from volunteer land stations), not a bug, so an empty answer is normal.
  - A wrong key is not answered with JSON: the connection is dropped with no close frame (code 1006) right after the subscription.
  - About one message in three is static data (ShipStaticData from class A ships, StaticDataReport from class B boats).
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
from .base import ProviderError
from .keyed import KeyedProvider

CAPABILITY = "ais"
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ais_stream_recording.json"
STATIC_KEEP = 4000  # remembered static records (about 1 MB)
STATIC_TTL_S = 6 * 3600.0
POSITION_KEEP = 4000  # remembered last positions (one small dict per ship)
POSITION_TTL_S = 300.0  # a position older than 5 minutes is never shown again: a ship moves, so an old fix is a wrong fix
MAX_SECONDS = 15.0
MAX_MESSAGES = 5000
CONNECT_TIMEOUT_S = 8.0


def _closed(e: Exception) -> str:
    """A screen-ready line for a connection the service closed. Only the close code and reason: never anything that could hold the key."""
    rcvd = getattr(e, "rcvd", None)
    code = getattr(rcvd, "code", None)
    reason = (getattr(rcvd, "reason", "") or "")[:60]
    if code is None:
        # No close frame at all: this is exactly what the live service did with a wrong key (checked 2026-11-05). It is also what a dropped
        # network or an overloaded beta service looks like, so it is worded as the most likely cause, not as a fact.
        return "AISSTREAM DROPPED THE CONNECTION WITH NO REASON: MOST OFTEN A WRONG KEY (CHECK IT IN APIKEYS), ELSE THE 3-CONNECTION LIMIT OR THE BETA SERVICE IS DOWN"
    return f"AISSTREAM CLOSED THE CONNECTION ({f'{code} {reason}'.strip()}): A REFUSED KEY, THE 3-CONNECTION LIMIT OR THE BETA SERVICE IS DOWN"


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


class PositionMemory:
    """The last position seen per ship (MMSI), kept for a few minutes so a sparse feed still fills a box over repeated listens.

    Why: the free feed carries ~80 messages a second for the WHOLE world, so one 15 s listen in a strait often sees 0-3 ships although
    more passed through. A ship that reported 2 minutes ago is still almost where it was, so showing it (clearly marked as remembered,
    with its age) is more honest than a blank panel, as long as it is never shown past `ttl_s`.

    Design choices (all deliberate):
      - Keyed by MMSI and independent of any box: one ship, one latest position. The box is applied only when we ANSWER (`recall`), so a ship
        that has left the box asked about is not returned, and a listen of one area never hides a ship remembered from another.
      - Pure and clock-free: every method takes `now` (epoch seconds), so tests run time forward without sleeping.
      - Bounded two ways: entries older than `ttl_s` are dropped, and if more than `keep` ships remain the least recently UPDATED ones go first
        (an OrderedDict, with `move_to_end` on every update, is the oldest-first queue).
    """

    def __init__(self, keep: int = POSITION_KEEP, ttl_s: float = POSITION_TTL_S):
        self.keep, self.ttl_s = keep, ttl_s
        self._by_mmsi: OrderedDict[int, dict[str, Any]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._by_mmsi)

    def age(self, p: dict[str, Any], now: float) -> float:
        """Seconds since the ship's last report. Uses the OLDER of the message's own clock (`seen`) and when we received it (`rx`), so a
        late-delivered or clock-skewed message can never make an old fix look young."""
        return now - min(p["seen"], p["rx"])

    def update(self, fresh: dict[int, dict[str, Any]], now: float) -> None:
        """Stores this listen's newest position per ship (a fresh one always replaces the remembered one), then drops expired and surplus entries."""
        for mmsi, p in fresh.items():
            self._by_mmsi[mmsi] = {**p, "rx": now}  # a copy: the caller's dict keeps its own flags
            self._by_mmsi.move_to_end(mmsi)  # most recently updated = last = evicted last
        for mmsi in [m for m, p in self._by_mmsi.items() if self.age(p, now) > self.ttl_s]:
            del self._by_mmsi[mmsi]
        while len(self._by_mmsi) > self.keep:
            self._by_mmsi.popitem(last=False)  # the least recently updated ship

    def recall(self, box: tuple[float, float, float, float], skip: set[int], now: float) -> dict[int, dict[str, Any]]:
        """Remembered ships inside `box` (south, west, north, east), not in `skip` (the ships this listen just saw) and no older than `ttl_s`."""
        south, west, north, east = box
        out = {}
        for mmsi, p in self._by_mmsi.items():
            if mmsi in skip or self.age(p, now) > self.ttl_s:
                continue
            if south <= p["lat"] <= north and west <= p["lon"] <= east:  # check_box guarantees west < east: boxes never cross the date line
                out[mmsi] = {k: v for k, v in p.items() if k != "rx"}
        return out


class AisStreamProvider(KeyedProvider):
    name = "aisstream"
    label = "AISstream (free key, beta WebSocket)"
    capabilities = frozenset({CAPABILITY})
    markets = "Live ship positions (AIS) inside a bounding box, plus destination and ETA as ships report them"
    terms = "Free key (AISSTREAM_API_KEY). BETA: no uptime promise, no replay, 3 connections per account and per IP. Positions are as reported by ships."
    key_name = "AISSTREAM_API_KEY"
    hide_without_key = False  # supports() stays true; a missing key answers KEY REQUIRED. (It uses a WebSocket, not KeyedProvider's HTTP request.)
    url = ap.URL  # tests point this at a local server

    def __init__(self, http: Any, source: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        self.source = "aisstream (REPLAY of a real recording from 2026-11-05, NOT LIVE)" if self.fixture else "aisstream"
        self._lock = asyncio.Lock()  # one listen at a time: the account allows only 3 connections
        self._statics: OrderedDict[int, dict[str, Any]] = OrderedDict()
        # Last position per ship for 5 minutes. It lives on this provider object, and the provider is built with the app, so a new app
        # (every test builds its own) starts with an empty memory. Fixture mode never touches it (see `_assemble`).
        self.positions = PositionMemory()
        self.clock = time.time  # tests replace this with a fake clock to age the memory without sleeping

    async def ais_listen(self, box: tuple[float, float, float, float], seconds: float = 8.0, max_messages: int = 3000) -> dict[str, Any]:
        """Listens inside `box` for at most `seconds` or `max_messages` data messages, whichever comes first.

        Returns {"positions": {mmsi: newest position}, "statics": {mmsi: static record}, "received": n data messages, "capped": hit the message cap,
        "listened_s": how long we actually listened, "source", "remembered": n ships that came from memory, "memory_s": the memory's limit}.
        `positions` holds this listen's ships (`remembered: False`) PLUS ships remembered from earlier listens that are still inside `box` and
        at most `POSITION_TTL_S` old (`remembered: True`). An empty `positions` is a real answer (quiet area or slow feed), not an error.
        """
        if not self._key:
            raise ProviderError("key_required", "AISSTREAM_API_KEY is not set")
        box = ap.check_box(*box)  # ValueError for a bad box, before any connection
        seconds, max_messages = min(max(seconds, 0.2), MAX_SECONDS), min(max(max_messages, 1), MAX_MESSAGES)
        async with self._lock:
            if self.fixture:
                msgs, listened = self._fixture_messages(box), 0.1
            else:
                msgs, listened = await self._read(box, seconds, max_messages)
            return self._assemble(msgs, listened, max_messages, box)

    # --- reading -----------------------------------------------------------------------------------------------------------
    def _fixture_messages(self, box: tuple[float, float, float, float]) -> list[dict[str, Any]]:
        """The recorded data messages that lie inside `box` (the live service filters by box too), so `AIS SUEZ` replays nothing and
        `AIS MALACCA` replays the Singapore Strait ships. The recorded confirmation is dropped, as `_read` does not count it either."""
        south, west, north, east = box
        out = []
        for msg in json.loads(FIXTURE.read_text(encoding="utf-8"))["messages"]:
            meta = msg.get("MetaData")
            if meta and south <= meta["latitude"] <= north and west <= meta["longitude"] <= east:
                out.append(msg)
        return out

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
    def _assemble(self, msgs: list[dict[str, Any]], listened: float, cap: int, box: tuple[float, float, float, float]) -> dict[str, Any]:
        now = self.clock()
        positions: dict[int, dict[str, Any]] = {}
        for msg in msgs:
            kind = ap.kind_of(msg)
            if kind == "position" and (p := ap.position(msg, now)) is not None:
                old = positions.get(p["mmsi"])
                if old is None or p["seen"] >= old["seen"]:
                    positions[p["mmsi"]] = p
            elif kind == "static" and (s := ap.static(msg, now)) is not None:
                s["rx"] = now  # when WE got it: the memory's age is measured from here, whatever the message's own clock says
                old = self._statics.get(s["mmsi"])
                if s.pop("partial") and old is not None:
                    # A class B boat sends its name and its type/size in separate messages: keep what the earlier part told us.
                    s = {**old, **{k: v for k, v in s.items() if v is not None}}
                self._statics[s["mmsi"]] = s
                self._statics.move_to_end(s["mmsi"])
        while len(self._statics) > STATIC_KEEP:
            self._statics.popitem(last=False)
        for mmsi in [m for m, s in self._statics.items() if now - s["rx"] > STATIC_TTL_S]:
            del self._statics[mmsi]
        # Position memory. Order matters: first remember what this listen saw (fresh always replaces older), then answer with this listen's
        # ships plus the remembered ones that are in THIS box, not already fresh, and young enough. Fixture mode is a replay of a recording:
        # it neither stores nor recalls, so a replay stays deterministic and nothing can leak from one test or panel to the next.
        positions = {m: {**p, "remembered": False} for m, p in positions.items()}
        remembered: dict[int, dict[str, Any]] = {}
        if not self.fixture:
            self.positions.update(positions, now)
            remembered = {m: {**p, "remembered": True} for m, p in self.positions.recall(box, set(positions), now).items()}
        positions |= remembered
        return {
            "positions": positions,
            "statics": {m: self._statics[m] for m in positions if m in self._statics},
            "remembered": len(remembered),
            "memory_s": self.positions.ttl_s,
            "received": len(msgs),
            "capped": len(msgs) >= cap,
            "listened_s": round(listened, 2),
            "source": self.source,
            "replay": self.fixture,  # True = a recording replayed in fixture mode, not the live feed
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
