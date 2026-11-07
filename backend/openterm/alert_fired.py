"""The one "alert fired" path (untangle B6).

Four places used to repeat the same steps after a store's `trigger()` answered: the price and news HTTP trigger routes
(`api.py`, called by a browser) and the price and news halves of the server engine (`alerts_engine.py`). Each one:

  1. checked `result["changed"]` (False = a second path already fired this alert: send nothing, so nothing repeats),
  2. built the subject and text with `delivery.format`,
  3. handed them to delivery with the alert's `VIA` channel list.

Only the engine also pushes a WebSocket `A` frame (its open tabs must refresh; the browser that called a route already knows).
That single difference is the `broadcast` parameter below: routes leave it None, the engine passes `hub.broadcast`.
The engine alone also says WHO checked the rule (`checked=`), because its message goes to a phone with no browser involved.
"""

from __future__ import annotations

from collections.abc import Callable

from .delivery import format as dfmt

# A deliver hook = `(kind, ref, subject, text, extra, channels)`; `channels` is the alert's VIA list or None (= every enabled channel).
Deliver = Callable[[str, int, str, str, dict, "list[str] | None"], object]


def fired_message(kind: str, alert: dict, checked: str | None = None) -> tuple[str, str, dict]:
    """(subject, text, extra) for a fired alert row. `kind` is "alert" (price) or "news"; `extra` is the delivery log's payload.

    `checked` only applies to price alerts (the news message has no "who checked" line); None keeps the browser wording.
    """
    if kind == "alert":
        subject, text = dfmt.alert_message(alert) if checked is None else dfmt.alert_message(alert, checked=checked)
        return subject, text, {"kind": "alert", "symbol": alert["symbol"]}
    if kind == "news":
        subject, text = dfmt.news_alert_message(alert)
        return subject, text, {"kind": "news", "word": alert["word"]}
    raise ValueError(f"unknown alert kind {kind!r}")


def announce(kind: str, result: dict, deliver: Deliver, *, broadcast: Callable[[list], object] | None = None,
             checked: str | None = None) -> bool:
    """Runs steps 1-3 for one `store.trigger()` answer. Returns True when the alert fired now (False = already triggered, nothing sent).

    `broadcast` (engine only) is called with the `["A", kind, id]` frame BEFORE delivery, as the engine always did.
    """
    if not result["changed"]:
        return False
    alert = result["alert"]
    if broadcast is not None:
        broadcast(["A", "price" if kind == "alert" else kind, alert["id"]])  # the frame says "price", the delivery kind says "alert"
    subject, text, extra = fired_message(kind, alert, checked)
    deliver(kind, alert["id"], subject, text, extra, alert["channels"])
    return True


def route_deliver(app) -> Deliver:
    """The deliver hook the HTTP routes use: `alert_channels.spawn` in the background, always with the alert's channel list."""

    def deliver(kind, ref, subject, text, extra, channels):
        from .alert_channels import spawn  # looked up at call time (tests replace it)

        return spawn(app, kind, ref, subject, text, extra, channels=channels)

    return deliver
