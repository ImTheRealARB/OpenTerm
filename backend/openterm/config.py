from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Secrets and host settings come from .env; everything else from config.yaml."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openterm_host: str = "127.0.0.1"
    openterm_port: int = 8000
    openterm_db_path: str = "data/openterm.db"
    # SEC asks for "Name email". Empty = a generic agent plus a hint on SOURCES (providers/sec.py).
    sec_user_agent: str = ""
    # Replay recorded provider responses instead of the network (tests, bench). Tagged in the UI.
    openterm_fixtures: bool = False
    # SYNxxxx random-walk instruments + tick stream for load testing. Labelled SYNTHETIC in the UI.
    openterm_synthetic: bool = False
    openterm_synthetic_tps: float = 20.0

    finnhub_api_key: str = ""
    twelvedata_api_key: str = ""
    alphavantage_api_key: str = ""
    fred_api_key: str = ""
    fmp_api_key: str = ""
    polygon_api_key: str = ""

    # --- Phase 10 ---
    # Serve a built frontend (frontend/dist) from the backend at "/". Empty = off (dev mode uses Vite).
    # Docker and the desktop build set it.
    openterm_static_dir: str = ""

    # --- Phase 11 ---
    # Key store backend: auto (OS keyring if one exists, else .env) | memory (tests) | none (.env only).
    openterm_keyring: str = "auto"
    # File the key store reads and, without a keyring, writes. Empty = .env at the repo root.
    openterm_dotenv_path: str = ""
    # Job worker processes. 0 = min(4, cpu_count - 1).
    openterm_job_workers: int = 0

    @property
    def yaml(self) -> dict:
        return load_yaml()


@lru_cache
def load_yaml() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
