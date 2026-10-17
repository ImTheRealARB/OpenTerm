import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App in fixture + synthetic mode: no network, recorded responses, SYNxxxx test instruments."""
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_SYNTHETIC", "1")
    monkeypatch.setenv("OPENTERM_SYNTHETIC_TPS", "50")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "api.db"))
    from openterm.config import get_settings

    get_settings.cache_clear()
    from openterm.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
