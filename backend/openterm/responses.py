import orjson
from fastapi.responses import Response


class Orjson(Response):
    """orjson for untyped dict payloads (FastAPI's built-in ORJSONResponse is deprecated)."""

    media_type = "application/json"

    def render(self, content) -> bytes:
        return orjson.dumps(content)
