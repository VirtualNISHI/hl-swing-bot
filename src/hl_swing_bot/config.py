"""Configuration loaded from environment variables / .env file."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    data_dir: Path = Field(default=PROJECT_ROOT / "data", alias="DATA_DIR")

    hl_coin: str = Field(default="BTC", alias="HL_COIN")
    hl_candle_interval: str = Field(default="1m", alias="HL_CANDLE_INTERVAL")
    hl_lookback_minutes: int = Field(default=120, alias="HL_LOOKBACK_MINUTES")

    @property
    def duckdb_path(self) -> Path:
        return self.data_dir / "market.duckdb"


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
