"""`DataError`: the one exception the data layer (service, world/*, derivs/*, research/*, kite/*) raises toward the HTTP layer.

It used to live in `service.py`, so every module that only wanted the exception had to import the whole data service, and the Kite
modules imported it inside functions to avoid an import cycle. Here it imports nothing from the app, so any module can import it at the
top of the file with no cycle. (Same idea as `errkinds.py`, which holds the kind words.)
"""


class DataError(Exception):
    """kind: a word from `errkinds` (bad_request | not_found | unavailable | key_required | ...). `detail` names each provider's reason;
    `key` names the missing key (key_required only)."""

    def __init__(self, kind: str, message: str, detail: str | None = None, key: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail
        self.key = key
