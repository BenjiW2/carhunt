"""CarGurus dealer-inventory scraper (Playwright, headed-preferred).

Behind a hard bot-wall (returns 403 to headless). Run with `--headed`. See
`_dealer.BrowserDealerScraper` for the strategy.
"""

from __future__ import annotations

from ..config import Config
from ._dealer import BrowserDealerScraper


class CarGurusScraper(BrowserDealerScraper):
    name = "cargurus"
    base = "https://www.cargurus.com"
    DETAIL_SUBSTRS = ["#listing=", "vdp.action", "listingId", "/Cars/link/"]

    def search_url(self, config: Config, page: int = 1) -> str:
        # CarGurus pagination is unreliable; page 2+ returns the same set, so the
        # base's de-dupe naturally stops after one page.
        return (
            "https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
            f"?zip={config.cars_zip}&maxPrice={config.max_price}"
            f"&distance={config.cars_radius}&sortDir=ASC&sourceContext=carGurusHomePageModel"
        )
