"""Gemini audit 2026-11 group 1 (docs/review/TRIAGE.md): C-01 strategy sandbox escape, C-02 loopback gating.

C-01 was reproduced: a string annotation evaluated by `typing.get_type_hints` ran with the REAL builtins (the class's
module `strategy` was not in sys.modules, so typing fell back to an empty namespace and Python filled it with the real
builtins), and a thread started from strategy code ran outside the per-thread runtime guard.
"""

import threading

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from openterm.bt import sandbox

TAIL = "\nclass SignalEngine:\n    def generate(self, data_map):\n        return {}\n"
_REAL_DISABLE_NETWORK = sandbox.disable_network
_SOCKET_NAMES = ("socket", "create_connection", "getaddrinfo", "gethostbyname", "socketpair", "fromfd")


@pytest.fixture(autouse=True)
def _keep_sockets(monkeypatch):
    # `load()` turns sockets off for the whole process (right for a job worker, fatal for the test process: the app's
    # event loop needs a socketpair). Same approach as test_sandbox_escape.
    monkeypatch.setattr(sandbox, "disable_network", lambda: None)


# --- layer 1: the static check refuses the string evaluators --------------------------------------------------------

@pytest.mark.parametrize("snippet", [
    "import typing\nclass P:\n    a: 'x'\nh = typing.get_type_hints(P)",
    "from typing import get_type_hints",
    "import typing\nr = typing.ForwardRef('x')",
    "from typing import ForwardRef",
    "import dataclasses\nh = dataclasses.typing.get_type_hints",
])
def test_string_evaluators_are_refused(snippet):
    with pytest.raises(sandbox.SandboxError):
        sandbox.check(snippet + TAIL)


def test_honest_typing_still_passes():
    # Type hints as documentation are fine; only the functions that EVALUATE annotation strings are refused.
    sandbox.check("from typing import Dict, List, Optional\nimport typing\nx: Optional[int] = None\n"
                  "y: typing.Dict[str, float] = {}\n" + TAIL)


# --- layer 2: what strategy code can reach at run time --------------------------------------------------------------

def test_an_escaped_evaluation_still_cannot_leave_the_guard():
    """Backstop for C-01: if some path ever evaluates a string with the real builtins inside strategy code (what
    `get_type_hints` on a class did), the payload Gemini used still fails: the thread start is vetoed."""
    payload = "[__import__('threading').Thread(target=lambda: None).start(), 1][1]"
    with sandbox.strict(), pytest.raises(PermissionError):
        eval(payload, {})  # an empty globals dict gets the REAL builtins, exactly like the escape


def test_three_argument_type_is_refused():
    with pytest.raises(TypeError):
        sandbox.load("X = type('X', (dict,), {})\n" + TAIL)


def test_one_argument_type_still_works():
    # `type(x)` as a type check is what honest strategies use it for.
    eng = sandbox.load("class SignalEngine:\n    def generate(self, data_map):\n"
                       "        return {'k': type(1) is int}\n")
    assert eng.generate({}) == {"k": True}


def test_generate_returns_a_plain_dict_built_inside_the_guard():
    eng = sandbox.load("import pandas as pd\nclass SignalEngine:\n    def generate(self, data_map):\n"
                       "        return {'A': pd.Series([1.0])}\n")
    out = eng.generate({})
    assert type(out) is dict and isinstance(out["A"], pd.Series)


# --- layer 3: the runtime guard -------------------------------------------------------------------------------------

def test_threads_cannot_be_started_inside_strict():
    with sandbox.strict(), pytest.raises(PermissionError):
        threading.Thread(target=lambda: None).start()


def test_raw_socket_is_refused_inside_strict():
    import _socket

    with sandbox.strict(), pytest.raises(PermissionError):
        _socket.socket()


def test_gemini_repro_thread_escape_is_blocked():
    """The exact C-01 repro: a strategy whose annotation starts a thread that lists the host folder."""
    code = ("import typing\nclass Probe:\n"
            "    a: \"[__import__('threading').Thread(target=lambda: print(__import__('os').listdir('.'))).start(),1][1]\"\n"
            "class SignalEngine:\n    def generate(self, data_map):\n        typing.get_type_hints(Probe)\n"
            "        return {}\n")
    with pytest.raises(sandbox.SandboxError):
        sandbox.check(code)


def test_disable_network_keeps_socket_subclassable():
    """M-09: `socket.socket` replaced by a bare function broke any later `import ssl` (ssl subclasses socket)."""
    import socket

    saved = {n: getattr(socket, n) for n in _SOCKET_NAMES if hasattr(socket, n)}
    try:
        _REAL_DISABLE_NETWORK()

        class Sub(socket.socket):  # what ssl.SSLSocket does at import time
            pass

        with pytest.raises(OSError):
            socket.socket()
        with pytest.raises(OSError):
            Sub()
    finally:
        for n, v in saved.items():
            setattr(socket, n, v)


# --- C-02: remote callers cannot change settings or submit inline Python --------------------------------------------

def _other(client):
    return TestClient(client.app, client=("203.0.113.9", 5))


def test_put_settings_is_loopback_only(client):
    cur = client.get("/api/settings").json()
    r = _other(client).put("/api/settings", json={"settings": cur["settings"] or {}, "version": cur["version"]})
    assert r.status_code == 403
    assert "THIS MACHINE" in r.text


def test_bt_run_with_inline_code_is_loopback_only(client):
    code = "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n"
    r = _other(client).post("/api/bt/run", json={"symbols": ["SYN0001"], "code": code})
    assert r.status_code == 403
    assert "THIS MACHINE" in r.text


def test_bt_run_with_a_rule_is_still_allowed_remotely(client):
    r = _other(client).post("/api/bt/run", json={"symbols": ["SYN0001"], "rule": "SMA(5) > SMA(20)"})
    assert r.status_code != 403


def test_settings_writes_from_this_machine_still_work(client):
    cur = client.get("/api/settings").json()
    r = client.put("/api/settings", json={"settings": cur["settings"] or {}, "version": cur["version"]})
    assert r.status_code == 200

