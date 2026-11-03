"""Facebook Marketplace: phase-2 stub, off by default (`ENABLE_FACEBOOK_MARKETPLACE`).

Why it is hard: there is no public API for Marketplace listings, the site sits behind a login
wall, and automated access violates Meta's terms and gets accounts banned. Options to try later:
an official partner/data programme, a user-supplied export, or a manual-assist browser flow.
To enable it: implement `search` below and flip the flag; nothing else needs to change.
"""

from __future__ import annotations

from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing

SOURCE_NAME = "facebook"


class FacebookMarketplaceSource:
    name = SOURCE_NAME

    async def search(
        self, query: ExpandedQuery, city: City | None, filters: Filters
    ) -> list[Listing]:
        raise NotImplementedError("Facebook Marketplace is not implemented (phase 2)")
