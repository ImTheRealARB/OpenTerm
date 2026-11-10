"""One exception for everything an order can run into. `kind` picks the HTTP status in routes.py."""

STATUS = {"bad_request": 400, "forbidden": 403, "not_found": 404, "confirm_required": 409, "mandate": 422, "broker_rejected": 422,
          "kill_switch": 423, "key_required": 424, "login_required": 401, "login_expired": 403, "mode_mismatch": 409,
          "live_off": 403, "unavailable": 503}


class OrderError(Exception):
    def __init__(self, kind: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail
