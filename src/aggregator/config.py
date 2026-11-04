"""Application settings, loaded from environment variables (and an optional `.env` file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: object) -> object:
    """Turn `"a, b ,c"` into `["a", "b", "c"]`; pass anything else through untouched."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram bot -------------------------------------------------------------------
    bot_token: str = ""
    # Private mode: only these Telegram user ids may use the bot. Empty list = public.
    allowed_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # --- Telegram reader account (Telethon, read-only) ---------------------------------
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: str = "./data/reader.session"
    # Group usernames or invite/t.me links, comma separated.
    telegram_groups: Annotated[list[str], NoDecode] = Field(default_factory=list)
    telegram_backfill_days: int = 30

    # --- LLM query expansion -----------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    anthropic_timeout_seconds: float = 8.0

    # --- Database ----------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://aggregator:aggregator@localhost:5432/aggregator"

    # --- Sources -----------------------------------------------------------------------
    enabled_sources: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["bazaraki", "telegram"]
    )
    enable_facebook_marketplace: bool = False
    source_timeout_seconds: float = 12.0
    bazaraki_cache_ttl_seconds: int = 300
    bazaraki_min_request_interval_seconds: float = 1.0
    bazaraki_max_pages: int = 3
    # Distinct search terms sent to Bazaraki per user search (primary + variants).
    bazaraki_max_terms: int = 2
    bazaraki_user_agent: str = (
        "TrevorTheHelperBot/0.1 (personal portfolio project; low-volume, cached)"
    )

    # --- Listings / analytics ----------------------------------------------------------
    listing_max_age_days: int = 30
    best_deal_ratio: float = 0.75
    # The "Best deals" block in the results message. Off until relevance tuning is good enough
    # that the median it is based on is not polluted by accessories and parts.
    show_best_deals: bool = False
    # Listings scoring below this against the expanded query are dropped (0..1).
    relevance_min_score: float = 0.75
    max_query_length: int = 100
    # How long a user can page through / re-filter the last result set.
    result_session_ttl_seconds: int = 3600

    # --- Rate limiting / quota ---------------------------------------------------------
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 5
    rate_limit_window_seconds: int = 60

    # --- Runtime -----------------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    health_port: int = 8080
    # "polling" now; "webhook" is reserved (see bot/runner.py).
    bot_mode: str = "polling"

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_user_ids(cls, value: object) -> object:
        parsed = _split_csv(value)
        if isinstance(parsed, list):
            return [int(item) for item in parsed]
        return parsed

    @field_validator("telegram_groups", "enabled_sources", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def is_private_mode(self) -> bool:
        return bool(self.allowed_user_ids)


@lru_cache
def get_settings() -> Settings:
    return Settings()
