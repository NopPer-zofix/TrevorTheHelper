"""The monetization seam: every search goes through `check_quota`. Today it only honours the
per-user `is_allowed` flag; plans, daily limits and payments plug in here later."""

from __future__ import annotations

from dataclasses import dataclass

from aggregator.services.users import UserProfile


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: str | None = None


def check_quota(user: UserProfile) -> QuotaDecision:
    if not user.is_allowed:
        return QuotaDecision(False, "user_blocked")
    return QuotaDecision(True)
