"""AutoTrader.com dealer-inventory scraper (Playwright, headed-preferred).

Behind PerimeterX/Cloudflare bot management — run with `--headed` for any real
chance of getting through. See `_dealer.BrowserDealerScraper` for the strategy.
"""

from __future__ import annotations

from ..config import Config
from ._dealer import BrowserDealerScraper


class AutoTraderScraper(BrowserDealerScraper):
    name = "autotrader"
    base = "https://www.autotrader.com"
    DETAIL_SUBSTRS = ["/cars-for-sale/vehicle", "vehicledetails", "listingId"]

    PAGE_SIZE = 50

    def search_url(self, config: Config, page: int = 1) -> str:
        url = (
            "https://www.autotrader.com/cars-for-sale/all-cars"
            f"?zip={config.cars_zip}&searchRadius={config.cars_radius}"
            f"&maxPrice={config.max_price}"
            "&listingTypes=USED"                 # used only
            "&sortBy=derivedpriceASC"            # cheapest first
            f"&numRecords={self.PAGE_SIZE}"
            f"&firstRecord={(page - 1) * self.PAGE_SIZE}"   # offset-based pagination
        )
        if config.min_price:
            url += f"&minPrice={config.min_price}"
        return url
