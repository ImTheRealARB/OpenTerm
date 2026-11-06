"""Audit D-1: the strategy sandbox must not be walkable through an allowed module's attributes, and the runtime guard
must veto file / process / network access even when the static check is bypassed."""

import os
import socket
import subprocess

import pandas as pd
import pytest

from openterm.bt import sandbox

TAIL = "\nclass SignalEngine:\n    def generate(self, data_map):\n        return {}\n"


@pytest.mark.parametrize("snippet", [
    "import dataclasses\nb = dataclasses.sys.modules['builtins']",
    "import typing\nx = typing.sys",
    "import functools\nx = functools.sys.modules['os'].popen('whoami')",
    "import pandas as pd\nx = pd.compat.os",
    "import pandas as pd\nx = pd.compat",
    "import numpy as np\nx = np.os.environ",
    "import collections\nx = collections.sys",
    "import datetime\nx = datetime.sys",
    "import dataclasses\nx = dataclasses.builtins.open",
    "import dataclasses\nx = dataclasses.os.listdir('.')",
    "import dataclasses\nx = dataclasses.subprocess",
    "from dataclasses import sys",
    "from typing import sys",
    "from pandas import compat",
    "import dataclasses\nx = dataclasses.exec",
    "import pandas as pd\nx = pd.eval",
])
def test_module_attribute_escapes_are_refused(snippet):
    with pytest.raises(sandbox.SandboxError):
        sandbox.check(snippet + TAIL)


def test_honest_attribute_names_still_pass():
    # OHLC columns and everyday methods must not be caught by the denylist.
    sandbox.check("import pandas as pd\nimport numpy as np\nfrom typing import Dict\n"
                  "class SignalEngine:\n    def generate(self, data_map):\n        out = {}\n"
                  "        for s, df in data_map.items():\n"
                  "            x = df.open.rename('a').replace(0, 1)\n"
                  "            out[s] = pd.Series(np.r_[x.values], index=df.index)\n        return out\n")


def _strict_denied(fn):
    with sandbox.strict(), pytest.raises(PermissionError):
        fn()


def test_runtime_guard_vetoes_files_processes_and_sockets(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("KEY=1")
    _strict_denied(lambda: open(secret).read())  # noqa: SIM115
    _strict_denied(lambda: open(tmp_path / "new.txt", "w"))  # noqa: SIM115
    _strict_denied(lambda: os.listdir(tmp_path))
    _strict_denied(lambda: os.system("echo hi"))
    _strict_denied(lambda: subprocess.run(["cmd", "/c", "echo"], check=False))
    _strict_denied(lambda: os.remove(secret))
    _strict_denied(lambda: socket.create_connection(("127.0.0.1", 9)))


def test_runtime_guard_is_off_outside_strict(tmp_path):
    (tmp_path / "a.txt").write_text("ok")
    assert (tmp_path / "a.txt").read_text() == "ok"  # the hook stays installed but sleeps
    with sandbox.strict():
        pass
    assert os.listdir(tmp_path) == ["a.txt"]


def test_runtime_guard_allows_pandas_internals():
    # Lazy imports and the time-zone database are read inside the Python install: they must keep working.
    with sandbox.strict():
        ts = pd.Timestamp("2024-03-01 10:00").tz_localize("America/New_York").tz_convert("Asia/Kolkata")
        assert ts.year == 2024
        pd.Series([1.0, 2.0, 3.0]).rolling(2).mean()


def test_loaded_strategy_runs_guarded_and_cannot_reach_the_os(monkeypatch):
    monkeypatch.setattr(sandbox, "disable_network", lambda: None)
    code = ("import pandas as pd\nclass SignalEngine:\n    def generate(self, data_map):\n"
            "        return {s: pd.Series(1.0, index=df.index) for s, df in data_map.items()}\n")
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))
    out = sandbox.load(code).generate({"A": df})
    assert list(out["A"]) == [1.0, 1.0]
