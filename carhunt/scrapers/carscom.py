"""Cars.com dealer-inventory scraper (Playwright) — EXPERIMENTAL.

Cars.com is the cleanest dealer-inventory target, but it sits behind a Cloudflare
JS challenge. In testing, headless Chromium clears that challenge only
intermittently; a real (headed) browser on your own machine is far more reliable.
So this scraper:
  • is opt-in (add "carscom" to `sources`),
  • strongly prefers headed mode (run with `--headed`),
  • degrades gracefully — if the challenge doesn't clear or no cards render, it
    returns [] with a clear message instead of breaking the run.

Cars.com listings include mileage and dealer name in the card grid, so they come
through richer than Facebook's.
"""

from __future__ import annotations

import re

from ..config import Config
from ..models import Listing
from ._browser import browser_context, wait_past_challenge
from .base import Scraper

PRICE_RE = re.compile(r"\$([\d,]+)")
MILEAGE_RE = re.compile(r"([\d,]+)\s*mi", re.I)
DETAIL_RE = re.compile(r"/vehicledetail/([0-9a-f-]+)/", re.I)


class CarsComScraper(Scraper):
    name = "carscom"

    def search(self, config: Config) -> list[Listing]:
        # Cars.com keys location off ZIP; fall back to a SF ZIP if none given.
        zip_code = config.cars_zip or "94103"
        url = (
            "https://www.cars.com/shopping/results/"
            f"?stock_type=used&maximum_price={config.max_price}"
            f"&zip={zip_code}&maximum_distance={config.cars_radius}"
            "&page_size=50&sort=best_match_desc"
        )

        with browser_context(headed=config.headed) as page:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if not wait_past_challenge(page, timeout_s=30):
                print(
                    "  ⚠ cars.com: Cloudflare challenge didn't clear "
                    f"({'headed' if config.headed else 'headless'}). "
                    "Try again, or run with --headed. Skipping cars.com."
                )
                return []

            # Cards lazy-render after the challenge; wait for them to appear.
            try:
                page.wait_for_selector(".vehicle-card, [data-test='vehicleCard']", timeout=15000)
            except Exception:
                print("  ⚠ cars.com: no listing cards rendered. Skipping.")
                return []
            page.wait_for_timeout(1500)

            cards = page.query_selector_all(".vehicle-card") or page.query_selector_all(
                "[data-test='vehicleCard']"
            )
            listings: list[Listing] = []
            for c in cards:
                parsed = self._parse_card(c)
                if parsed:
                    listings.append(parsed)
            return listings

    def _parse_card(self, card) -> Listing | None:
        def txt(*selectors: str) -> str | None:
            for sel in selectors:
                el = card.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if t:
                        return t
            return None

        title = txt("h2.title", ".title", "[data-test='vehicleListingTitle']")
        if not title:
            return None

        price = None
        if (pt := txt(".primary-price", "[data-test='vehicleCardPricingBlockPrice']")):
            if m := PRICE_RE.search(pt):
                price = int(m.group(1).replace(",", ""))

        mileage = None
        if (mt := txt(".mileage", "[data-test='vehicleMileage']")):
            if m := MILEAGE_RE.search(mt):
                mileage = int(m.group(1).replace(",", ""))

        link = card.query_selector("a[href*='/vehicledetail/']")
        href = link.get_attribute("href") if link else None
        if href and href.startswith("/"):
            href = "https://www.cars.com" + href
        if not href:
            return None
        idm = DETAIL_RE.search(href)

        return Listing(
            source=self.name,
            id=idm.group(1) if idm else href,
            title=title,
            price=price,
            mileage=mileage,
            location=txt(".dealer-name", ".miles-from"),
            url=href.split("?")[0],
        )
