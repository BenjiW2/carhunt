"""Facebook Marketplace scraper (Playwright, no login required).

Marketplace's public vehicle search renders without authentication and is not
behind Cloudflare, so a plain headless Chromium can read it. We load the city's
vehicle search, scroll to lazy-load more cards, and parse each listing from its
`/marketplace/item/<id>/` link text, which is reliably formatted as:

    "$8,400 | 1987 Volvo 240 Sedan 4D | Berkeley, CA"

Mileage isn't shown in the card grid (it lives on the detail page), so FB
listings come through without mileage — the scorer leans on the year + model
reputation, which is in the title.
"""

from __future__ import annotations

import re

from ..config import Config
from ..models import Listing
from ..ui import progress_bar
from ._browser import persistent_context, wait_past_challenge
from .base import Scraper

ITEM_RE = re.compile(r"/marketplace/item/(\d+)")
PRICE_RE = re.compile(r"\$([\d,]+)")
MILEAGE_RE = re.compile(r"[Dd]riven\s+([\d,]+)\s*miles|([\d,]{4,6})\s*miles")
# The logged-in detail page exposes a "About this vehicle" specs block followed
# by the seller's free-text description; grab from there to the seller card.
DETAILS_RE = re.compile(
    r"About this vehicle(.*?)(?:Seller information|Seller details|Today's picks|Related)",
    re.S,
)


class FacebookScraper(Scraper):
    name = "facebook"

    def login(self, config: Config) -> None:
        """One-time interactive login. Opens a real browser; you log in by hand.

        The session is saved in `config.fb_session_dir`, so later runs are already
        authenticated. We never see or handle your password.
        """
        print(
            "Opening Facebook in a browser window.\n"
            "  1. Log in (and clear any checkpoint) in that window.\n"
            "  2. Come back here and press Enter to save the session."
        )
        with persistent_context(config.fb_session_dir, headed=True) as page:
            page.goto("https://www.facebook.com/login", timeout=60000)
            input("\nPress Enter once you're logged in… ")
        print(f"Session saved to {config.fb_session_dir}/. You can now scrape Facebook.")

    def search(self, config: Config) -> list[Listing]:
        city = config.fb_city or "sanfrancisco"
        url = (
            f"https://www.facebook.com/marketplace/{city}/vehicles"
            f"?maxPrice={config.max_price}&sortBy=creation_time_descend"
        )
        listings: dict[str, Listing] = {}

        # Facebook works fine headless and login persists, so never pop a window
        # for it — even when --headed is set for the Cloudflare dealer sites.
        with persistent_context(config.fb_session_dir, headed=False) as page:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            wait_past_challenge(page)
            page.wait_for_timeout(4000)

            # A visible login field means we're browsing anonymously (capped ~24).
            if page.query_selector("input[name='pass']"):
                print(
                    "  ⚠ facebook: not logged in — anonymous view is capped at ~24 "
                    "listings. Run `python -m carhunt --fb-login` once to unlock more."
                )

            # Scroll until we stop finding new listings (or hit the caps).
            stale_rounds = 0
            for _ in range(config.fb_scrolls):
                before = len(listings)
                self._harvest(page, listings)
                if len(listings) >= config.fb_max_listings:
                    break
                stale_rounds = 0 if len(listings) > before else stale_rounds + 1
                if stale_rounds >= 3:
                    break
                page.mouse.wheel(0, 6000)
                page.wait_for_timeout(2000)
            self._harvest(page, listings)

        return list(listings.values())[: config.fb_max_listings]

    def enrich(self, listings: list[Listing], config: Config) -> None:
        """Open each survivor's detail page in the browser to pull mileage.

        Only the listings that passed the cheap local filter reach here, so we
        pay the per-page load for ~the scoring cap, not all 150. Mileage is read
        from the "Driven N miles" text (works logged-in or anonymous); the full
        seller description needs a logged-in session.
        """
        with persistent_context(config.fb_session_dir, headed=False) as page:  # FB stays headless
            page.set_default_timeout(60000)
            with progress_bar("  facebook: detail pages", len(listings)) as advance:
                for lst in listings:
                    try:
                        page.goto(lst.url, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(3500)
                        body = page.inner_text("body")
                        if (mi := self._extract_mileage(body)) is not None:
                            lst.mileage = mi
                        lst.description = self._extract_details(body)
                    except Exception:  # noqa: BLE001 - one bad page shouldn't stop the batch
                        pass
                    advance()

    @staticmethod
    def _extract_mileage(body: str) -> int | None:
        m = MILEAGE_RE.search(body)
        if not m:
            return None
        raw = m.group(1) or m.group(2)
        try:
            return int(raw.replace(",", ""))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _extract_details(body: str) -> str | None:
        """Specs block + seller's free-text description (where 'doesn't run' lives)."""
        m = DETAILS_RE.search(body)
        if not m:
            return None
        text = re.sub(r"\s*\n\s*", " · ", m.group(1)).strip(" ·")
        return text[:1200] or None

    def _harvest(self, page, listings: dict[str, Listing]) -> None:
        for a in page.query_selector_all("a[href*='/marketplace/item/']"):
            href = (a.get_attribute("href") or "").split("?")[0]
            m = ITEM_RE.search(href)
            if not m:
                continue
            item_id = m.group(1)
            if item_id in listings:
                continue
            parsed = self._parse_card(item_id, a.inner_text())
            if parsed:
                listings[item_id] = parsed

    def _parse_card(self, item_id: str, text: str) -> Listing | None:
        # Card text: "$8,400\n1987 Volvo 240 Sedan 4D\nBerkeley, CA"
        parts = [p.strip() for p in text.split("\n") if p.strip()]
        if not parts:
            return None

        price = None
        title = None
        location = None
        for p in parts:
            pm = PRICE_RE.search(p)
            if pm and price is None:
                price = int(pm.group(1).replace(",", ""))
                continue
            # The first non-price line is the title; a trailing "City, ST" is location.
            if title is None:
                title = p
            elif re.search(r",\s*[A-Z]{2}$", p):
                location = p
        if not title:
            return None

        return Listing(
            source=self.name,
            id=item_id,
            title=title,
            price=price,
            location=location,
            url=f"https://www.facebook.com/marketplace/item/{item_id}/",
        )
