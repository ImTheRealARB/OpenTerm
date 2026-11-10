"""Orders (Phase 18, spec docs/specs/PHASE_18.md): order model, mandate, one-time confirm tokens, kill switch, broker adapters.

Rules this package enforces in code, not in the UI:
- An order reaches a broker only through `service.OrderService.submit`: kill switch off, key present, mode derived from the broker
  (host and account), live switched on by the user, mandate passed, and a fresh one-time confirm token issued for exactly that order.
- PAPER or LIVE is never read from a request. It comes from the broker adapter (the host its key slot talks to, checked against
  the account the broker returns).
- Every order event is written to the hash-chained audit ledger (kind `order`).
- Nothing in `ai/` or `mcp/` imports this package; tests scan both for order tools and routes.
"""

FIXTURE_LABEL = "DOC-SHAPED FIXTURE, NOT A RECORDING"
