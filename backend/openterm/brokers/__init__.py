"""Phase 18 step 2: READ-ONLY broker sync (Zerodha Kite holdings, Interactive Brokers Client Portal gateway) into PORT.

Everything here reads: it fetches what the broker already holds and writes OpenTerm portfolio lots. There is no code path that
sends an order, a modification or a cancellation to any broker, and a test scans this package for that. Alpaca is not part of it.
"""

FIXTURE_LABEL = "DOC-SHAPED FIXTURE, NOT A RECORDING"
