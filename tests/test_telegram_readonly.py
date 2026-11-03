"""The reader account must never write to Telegram. Guard against it at the source level."""

from __future__ import annotations

import re
from pathlib import Path

TELEGRAM_PACKAGE = (
    Path(__file__).resolve().parents[1] / "src" / "aggregator" / "sources" / "telegram"
)

# Telethon calls that send, change or delete content, or join/leave chats.
FORBIDDEN = re.compile(
    r"\b(send_\w+|forward_messages|edit_message|delete_messages|pin_message|unpin_message"
    r"|kick_participant|edit_permissions|edit_admin"
    r"|JoinChannelRequest|ImportChatInviteRequest|LeaveChannelRequest|DeleteMessagesRequest"
    r"|SendMessageRequest)\b"
    r"|\.(?:action|conversation)\("
)


def test_package_exists() -> None:
    assert (TELEGRAM_PACKAGE / "indexer.py").is_file()


def test_no_write_calls_in_telegram_package() -> None:
    offenders: list[str] = []
    for path in sorted(TELEGRAM_PACKAGE.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if FORBIDDEN.search(code):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "write-capable Telethon calls found:\n" + "\n".join(offenders)
