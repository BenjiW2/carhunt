"""AutoTrader.com scraper — scaffolded for the browser-automation phase.

AutoTrader sits behind bot protection (challenge pages / fingerprinting) that
blocks plain `requests`. Its results are also rendered from an embedded JSON
blob. When we add the Playwright phase, implement `search` here: drive a real
browser to the search results, read the `__NEXT_DATA__` / inventory JSON, and
map it into Listing objects. Cars.com is a similar shape and a good second
target.
"""

from __future__ import annotations

from ..config import Config
from ..models import Listing
from .base import Scraper


class AutoTraderScraper(Scraper):
    name = "autotrader"

    def search(self, config: Config) -> list[Listing]:
        raise NotImplementedError(
            "AutoTrader.com is behind bot protection and needs the browser-automation phase. "
            "Remove 'autotrader' from `sources` for now."
        )
