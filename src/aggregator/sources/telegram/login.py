"""One-time interactive login for the reader account: `make telegram-login`.

Asks for phone, login code and (if enabled) the 2FA password, then stores the session under
`./data/`. Run it in a terminal; the indexer container only reuses the saved session.
"""

from __future__ import annotations

import asyncio

from aggregator.config import get_settings
from aggregator.sources.telegram.client import build_client


async def main() -> None:
    settings = get_settings()
    client = build_client(settings)
    # `start()` prompts on stdin for the phone number, the code and the 2FA password as needed.
    await client.start()
    me = await client.get_me()
    label = getattr(me, "username", None) or getattr(me, "first_name", "")
    print(f"Logged in as {label}. Session saved to {settings.telegram_session_path}")
    await client.disconnect()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
