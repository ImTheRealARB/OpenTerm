"""Decoder for Yahoo's streamer messages: base64 protobuf `PricingData`.

Hand-rolled (no protobuf dependency): the wire format is varints, zigzag sint64, float32, float64
and length-delimited strings. Field numbers verified against live messages on 2026-10-17.
"""

import base64
import struct

# field number -> (name, kind). Kinds: str, f32, f64, sint (zigzag varint), int (plain varint)
FIELDS: dict[int, tuple[str, str]] = {
    1: ("id", "str"),
    2: ("price", "f32"),
    3: ("time", "sint"),  # epoch ms
    4: ("currency", "str"),
    5: ("exchange", "str"),
    6: ("quote_type", "int"),
    7: ("market_hours", "int"),
    8: ("change_pct", "f32"),
    9: ("day_volume", "sint"),
    10: ("day_high", "f32"),
    11: ("day_low", "f32"),
    12: ("change", "f32"),
    13: ("short_name", "str"),
    15: ("open", "f32"),
    16: ("prev_close", "f32"),
    22: ("last_size", "sint"),
    23: ("bid", "f32"),
    24: ("bid_size", "sint"),
    25: ("ask", "f32"),
    26: ("ask_size", "sint"),
    27: ("price_hint", "sint"),
    33: ("market_cap", "f64"),
}


def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        x = b[i]
        i += 1
        result |= (x & 0x7F) << shift
        if not x & 0x80:
            return result, i
        shift += 7


def decode(buf: bytes) -> dict:
    out: dict = {}
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        name, kind = FIELDS.get(field, (None, None))
        if wire == 0:
            v, i = _varint(buf, i)
            if kind == "sint":
                v = (v >> 1) ^ -(v & 1)
        elif wire == 1:
            v = struct.unpack_from("<d", buf, i)[0]
            i += 8
        elif wire == 2:
            ln, i = _varint(buf, i)
            v = buf[i : i + ln].decode("utf-8", "replace")
            i += ln
        elif wire == 5:
            v = struct.unpack_from("<f", buf, i)[0]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        if name:
            out[name] = v
    # float32 on the wire: round to the instrument's price hint to drop representation noise.
    digits = out.get("price_hint") or 4
    for k in ("price", "change", "day_high", "day_low", "open", "prev_close", "bid", "ask"):
        if k in out:
            out[k] = round(out[k], digits)
    if "change_pct" in out:
        out["change_pct"] = round(out["change_pct"], 4)
    return out


def decode_b64(message: str) -> dict:
    return decode(base64.b64decode(message))
