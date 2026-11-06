"""The error "kind" words, defined once.

Every failure in OpenTerm carries a short lowercase word (`kind`) that says what went wrong: a provider raises
`ProviderError(kind)`, the data service re-raises it as `DataError(kind)`, and the HTTP layer turns the kind into a status
code (`http_util.STATUS`). The words used to be typed out by hand in the router, the API and the provider base class, so a
typo in one place silently stopped matching in another. Now they live here, and the places that decide something based on
a kind (the router's circuit breaker, the status map) import them.

Plain strings on purpose: a kind is stored in JSON, compared with `==` and printed in logs, and a bare string does all of
that with no surprises. (An Enum would work too, but its members print and serialise differently.)

This module imports nothing from the app, so any module can import it without creating an import cycle.
"""

from typing import Final, Literal

# --- raised by providers (ProviderError) ---
NOT_FOUND: Final = "not_found"          # the source is fine, it just has nothing for this symbol
UNSUPPORTED: Final = "unsupported"      # the source does not cover this kind of symbol at all
DEPTH: Final = "depth"                  # the source has the symbol but not that far back (a request problem)
RATE_LIMITED: Final = "rate_limited"
UNAVAILABLE: Final = "unavailable"      # an outage or a bad answer: PROVIDER DOWN
KEY_REQUIRED: Final = "key_required"    # needs an API key set in APIKEYS
LOGIN_EXPIRED: Final = "login_expired"  # Kite's daily login ran out

# --- raised by the data service and user-data code (DataError / UserDataError), on top of the ones above ---
BAD_REQUEST: Final = "bad_request"
TOO_LARGE: Final = "too_large"
LOGIN_REQUIRED: Final = "login_required"

ProviderKind = Literal["not_found", "unsupported", "depth", "rate_limited", "unavailable", "key_required", "login_expired"]

# Kinds that say "the provider is healthy, it just can't answer this one": the circuit breaker must not count them as strikes.
NOT_AN_OUTAGE: Final = (NOT_FOUND, UNSUPPORTED, DEPTH, LOGIN_EXPIRED)
# Kinds that need something from the user (a key, a login): they are not an outage either, and are passed up unchanged.
NEEDS_USER_ACTION: Final = (KEY_REQUIRED, LOGIN_EXPIRED)
