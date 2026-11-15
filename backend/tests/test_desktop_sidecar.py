"""Desktop packaging pieces that can be tested without PyInstaller or Tauri (docs/DESKTOP.md, desktop/sidecar/).

The frozen executable itself is tested by desktop/sidecar/smoke.py (it needs a build); these cover the two small
changes the backend needed for it: OPENTERM_CONFIG_PATH, and the launcher's "stop when the shell is gone" watcher.
"""

import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from openterm import config

LAUNCHER = Path(__file__).resolve().parents[2] / "desktop" / "sidecar" / "launcher.py"


@pytest.fixture
def fresh_config(monkeypatch):
    """Both config readers are cached; clear them before and after so this test cannot leak into others."""
    config.get_settings.cache_clear()
    config.load_yaml.cache_clear()
    yield monkeypatch
    monkeypatch.undo()
    config.get_settings.cache_clear()
    config.load_yaml.cache_clear()


def test_config_path_points_at_another_file(fresh_config, tmp_path):
    f = tmp_path / "shipped.yaml"
    f.write_text("app:\n  default_market: IN\n", encoding="utf-8")
    fresh_config.setenv("OPENTERM_CONFIG_PATH", str(f))
    assert config.load_yaml() == {"app": {"default_market": "IN"}}


def test_config_path_that_does_not_exist_fails_loudly(fresh_config, tmp_path):
    fresh_config.setenv("OPENTERM_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    with pytest.raises(FileNotFoundError, match="OPENTERM_CONFIG_PATH"):
        config.load_yaml()


def test_no_config_path_still_reads_the_repo_file(fresh_config):
    fresh_config.delenv("OPENTERM_CONFIG_PATH", raising=False)
    assert "cache" in config.load_yaml()  # <repo>/config.yaml


def test_launcher_stops_the_server_when_its_parent_is_gone():
    spec = importlib.util.spec_from_file_location("sidecar_launcher", LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)  # importing must not start a server (main() is behind __name__)

    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()  # a pid that no longer exists
    server = SimpleNamespace(should_exit=False)
    t0 = time.monotonic()
    launcher.watch_parent(gone.pid, server)  # returns once it has asked the server to stop
    assert server.should_exit is True and time.monotonic() - t0 < 5
