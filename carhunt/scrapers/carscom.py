"""Cars.com dealer-inventory scraper (Playwright, headed-preferred).

Cars.com sits behind Cloudflare; run with `--headed`. It uses the shared
`BrowserDealerScraper` extraction (schema.org JSON-LD first, then a detail-link
heuristic) rather than CSS card classes, which change often. Cars.com vehicle
detail pages live under `/vehicledetail/<id>/`.
"""

from __future__ import annotations

from ..config import Config
from ._dealer import BrowserDealerScraper


class CarsComScraper(BrowserDealerScraper):
    name = "carscom"
    base = "https://www.cars.com"
    DETAIL_SUBSTRS = ["/vehicledetail/"]

    def search_url(self, config: Config, page: int = 1) -> str:
        url = (
            "https://www.cars.com/shopping/results/"
            "?stock_type=used"                       # used only
            f"&maximum_price={config.max_price}"
            f"&zip={config.cars_zip}&maximum_distance={config.cars_radius}"
            f"&page_size=50&sort=list_price&page={page}"   # cheapest first, paginated
        )
        if config.min_price:
            url += f"&minimum_price={config.min_price}"
        return url
