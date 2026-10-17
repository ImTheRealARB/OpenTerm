import time

import orjson
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from . import APP_NAME, __version__, perf

STARTED = time.time()


class Orjson(Response):
    """orjson for untyped dict payloads (FastAPI's built-in ORJSONResponse is deprecated)."""

    media_type = "application/json"

    def render(self, content) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_SERIALIZE_NUMPY)


app = FastAPI(title=APP_NAME, version=__version__, default_response_class=Orjson)
app.add_middleware(perf.TimingMiddleware)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "app": APP_NAME, "version": __version__, "uptime_s": time.time() - STARTED}


@app.get("/api/perf")
async def perf_summary() -> dict:
    return perf.summary()


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    """Multiplexed stream. Phase 1: ping/pong only; subscribe/unsubscribe land in phase 3.

    Frames are compact JSON arrays: ["pong", client_ts, server_ts].
    """
    await socket.accept()
    try:
        while True:
            msg = orjson.loads(await socket.receive_text())
            if msg and msg[0] == "ping":
                await socket.send_text(orjson.dumps(["pong", msg[1], time.time() * 1000]).decode())
    except WebSocketDisconnect:
        pass
