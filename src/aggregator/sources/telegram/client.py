"""Telethon client construction shared by the indexer and the interactive login."""

from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from aggregator.config import Settings


def session_base(configured_path: str) -> str:
    """Telethon appends `.session` itself; strip it so `./data/reader.session` isn't doubled."""
    path = Path(configured_path)
    if path.suffix == ".session":
        path = path.with_suffix("")
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def build_client(settings: Settings) -> TelegramClient:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set (my.telegram.org).")
    return TelegramClient(
        session_base(settings.telegram_session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
