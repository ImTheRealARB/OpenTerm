"""Pure message formatting for alert delivery (Phase 17 B). No I/O here, so it is trivial to unit-test.

Each function takes the alert row as the stores return it and gives back `(subject, text)`.
Plain text only: it must read the same in an email, a Telegram chat and a Slack/Discord webhook.
"""

from __future__ import annotations

import datetime as dt


def _when(ts) -> str:
    """Epoch seconds -> 'YYYY-MM-DD HH:MM UTC' (a message read hours later must say when it fired)."""
    if not isinstance(ts, (int, float)):
        return "time unknown"
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _num(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def alert_message(alert: dict, checked: str = "in the browser") -> tuple[str, str]:
    """Price alert row (symbol, op, unit, value, trigger_price, triggered_at) -> subject and body.

    `checked` says who evaluated the rule: the browser (the default, for a tab that fired it) or the server engine.
    """
    sym = alert.get("symbol", "?")
    word = "above" if alert.get("op") == ">" else "below"
    unit = "%" if alert.get("unit") == "pct" else ""
    rule = f"{word} {_num(alert.get('value'))}{unit}"
    price = alert.get("trigger_price")
    at_price = f"at {_num(price)}" if price is not None else "(price not reported)"
    subject = f"OpenTerm alert: {sym} {rule}"
    text = (f"{sym} crossed {rule}, {at_price}.\n"
            f"Fired {_when(alert.get('triggered_at'))}. Source: your OpenTerm alert rule, checked {checked}.")
    return subject, text


def news_alert_message(alert: dict) -> tuple[str, str]:
    """News keyword alert row (word, symbol, headline, url, triggered_at) -> subject and body."""
    word = alert.get("word", "?")
    sym = f" [{alert['symbol']}]" if alert.get("symbol") else ""
    subject = f"OpenTerm news alert: {word}{sym}"
    lines = [f"Headline matched {word}{sym}: {alert.get('headline') or '(no headline)'}"]
    if alert.get("url"):
        lines.append(alert["url"])
    lines.append(f"Fired {_when(alert.get('triggered_at'))}.")
    return subject, "\n".join(lines)


def test_message() -> tuple[str, str]:
    return "OpenTerm test message", "This is a test message from OpenTerm. If you can read it, this channel works."
