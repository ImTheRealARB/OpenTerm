"""Zerodha Kite Connect, READ-ONLY market data (Phase 15, spec docs/specs/PHASE_15.md "Kite Connect", decision K).

Bars, ticks, instruments and option chains with open interest, from the user's own paid Kite Connect app. Everything is inert without a
key in APIKEYS and without the daily login. This package reads market data only: it has no code path that sends anything to the
broker beyond the login exchange and data reads, and a test scans every file here for that.
"""

KITE_LOGIN = "https://kite.zerodha.com/connect/login"
KITE_API = "https://api.kite.trade"
KITE_WS = "wss://ws.kite.trade"
FIXTURE_LABEL = "DOC-SHAPED FIXTURE, NOT A RECORDING"
