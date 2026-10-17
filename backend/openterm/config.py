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
    sec_user_agent: str = "OpenTerm/0.1 contact@example.com"
    # Replay recorded provider responses instead of the network (tests, bench). Tagged in the UI.
    openterm_fixtures: bool = False

    finnhub_api_key: str = ""
    twelvedata_api_key: str = ""
    alphavantage_api_key: str = ""
    fred_api_key: str = ""
    fmp_api_key: str = ""
    polygon_api_key: str = ""

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
