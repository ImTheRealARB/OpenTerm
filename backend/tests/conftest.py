import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def hermetic_keys(tmp_path, monkeypatch):
    """Phase 11: no test touches the real OS keyring or the repo's .env, whichever app fixture it uses."""
    monkeypatch.setenv("OPENTERM_KEYRING", "memory")
    monkeypatch.setenv("OPENTERM_DOTENV_PATH", str(tmp_path / "keys.env"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App in fixture + synthetic mode: no network, recorded responses, SYNxxxx test instruments."""
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_SYNTHETIC", "1")
    monkeypatch.setenv("OPENTERM_SYNTHETIC_TPS", "50")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "api.db"))
    # Phase 11: never touch the real OS keyring or the repo's .env from tests; 2 job workers per xdist worker.
    monkeypatch.setenv("OPENTERM_KEYRING", "memory")
    monkeypatch.setenv("OPENTERM_DOTENV_PATH", str(tmp_path / "keys.env"))
    monkeypatch.setenv("OPENTERM_JOB_WORKERS", "2")
    from openterm.keys import KEY_SPECS

    for spec in KEY_SPECS.values():  # a key in the developer's own environment must not change test results
        for name in spec.fields:
            monkeypatch.delenv(name, raising=False)
    from openterm.config import get_settings

    get_settings.cache_clear()
    from openterm.main import app

    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c
    get_settings.cache_clear()
