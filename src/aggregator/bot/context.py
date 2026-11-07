"""What handlers receive via aiogram's dependency injection (`services` argument)."""

from __future__ import annotations

from dataclasses import dataclass

from aggregator.services.pending import PendingStore
from aggregator.services.search_service import SearchService
from aggregator.services.sessions import SessionStore
from aggregator.services.users import UserService


@dataclass
class Services:
    users: UserService
    search: SearchService
    sessions: SessionStore
    pending: PendingStore
    source_names: list[str]
    #: Whether the results message has the "Best deals" block (config: SHOW_BEST_DEALS).
    show_best_deals: bool = True
