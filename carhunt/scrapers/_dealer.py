"""Base for browser-driven dealer-inventory scrapers (AutoTrader, CarGurus, …).

These sites sit behind bot-walls (Cloudflare / PerimeterX). A headless browser
clears them only intermittently; a real headed browser on your own machine is
far more reliable — so these scrapers prefer `--headed` and always fail safe
(return [] with a message) rather than break the run.

Extraction tries two strategies, most-stable first:
  1. schema.org JSON-LD (`<script type="application/ld+json">`) — many car sites
     embed Vehicle/Car/Product offers with price, mileage, and URL.
  2. A DOM link-heuristic — find detail-page links and parse price/mileage/title
     from each card's text.

Because these run blind (I can't see the rendered page from here), expect to
tweak `DETAIL_SUBSTRS` / the search URL once you've watched it load headed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..config import Config
from ..models import Listing
from ._browser import browser_context, dismiss_consent, looks_blocked, wait_past_challenge
from .base import Scraper

PRICE_RE = re.compile(r"\$\s?([\d,]{3,7})")
MILEAGE_RE = re.compile(r"([\d,]{3,7})\s*(?:mi\b|miles)", re.I)
YEAR_RE = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")


class BrowserDealerScraper(Scraper):
    """Subclasses set: name, base, DETAIL_SUBSTRS, and search_url()."""

    name = "dealer"
    base = ""
    DETAIL_SUBSTRS: list[str] = []

    def search_url(self, config: Config, page: int = 1) -> str:  # pragma: no cover
        raise NotImplementedError

    def enrich(self, listings: list[Listing], config: Config) -> None:
        # Dealer listings already carry mileage from the search page, and detail
        # pages are behind the same bot-wall — nothing useful to fetch.
        return

    def search(self, config: Config) -> list[Listing]:
        out: dict[str, Listing] = {}
        with browser_context(headed=config.headed) as page:
            page.set_default_timeout(60000)
            for pnum in range(1, max(1, config.dealer_pages) + 1):
                if not self._load_page(page, self.search_url(config, pnum), first=(pnum == 1)):
                    break  # blocked / failed — stop paginating

                if os.getenv("CARHUNT_DUMP"):
                    dump = Path("results") / f"{self.name}_page{pnum}.html"
                    dump.parent.mkdir(parents=True, exist_ok=True)
                    dump.write_text(page.content())

                try:
                    jsonld = self._from_jsonld(page)
                    found = jsonld or self._from_links(page, config)
                except Exception:  # noqa: BLE001 - navigation race / redirect mid-query
                    print(f"  ⚠ {self.name}: page {pnum} navigated mid-scrape (likely a redirect/block); stopping.")
                    break
                new = sum(1 for l in found if l.url not in out and not out.update({l.url: l}))
                print(f"    {self.name}: page {pnum} -> {len(found)} listings ({new} new)")
                if new == 0:
                    break  # ran out of results (or duplicate page)

        listings = list(out.values())
        if listings:
            n_priced = sum(1 for l in listings if l.price)
            print(f"    {self.name}: {n_priced}/{len(listings)} have a price")
            for s in listings[:3]:
                print(f"      e.g. {s.title[:50]!r} | price={s.price} | mi={s.mileage}")
        else:
            print(f"  ⚠ {self.name}: no listings found (blocked or selectors need updating).")
        return listings

    def _load_page(self, page, url: str, first: bool) -> bool:
        """Navigate to one results page; clear the JS challenge and cookie banner.
        Returns False if the page failed to load or was bot-blocked."""
        for attempt in range(2):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                print(f"  ⚠ {self.name}: page didn't load.")
                return False
            if not wait_past_challenge(page, timeout_s=35):
                print(f"  ⚠ {self.name}: bot-wall didn't clear "
                      f"({'headed' if page.context.browser else 'headless'}); run with --headed.")
                return False
            page.wait_for_timeout(2500)
            if not looks_blocked(page):
                break
            if attempt == 0 and first:
                print(f"  ⚠ {self.name}: hit a bot-block page; pausing 6s and retrying once…")
                page.wait_for_timeout(6000)
            else:
                print(f"  ⚠ {self.name}: blocked by bot protection (Akamai/PerimeterX) — flaky; try later.")
                return False

        # Cookie banner is lazy and overlays the grid; dismiss it and let cards render.
        detail_sel = ", ".join(f"a[href*='{s}']" for s in self.DETAIL_SUBSTRS) or "a[href]"
        for _ in range(12):
            try:
                dismiss_consent(page)
                if len(page.query_selector_all(detail_sel)) >= 5:
                    break
            except Exception:  # noqa: BLE001 - page navigated under us; let it settle
                pass
            page.wait_for_timeout(800)
        page.wait_for_timeout(800)
        return True

    # --- strategy 1: structured data ---------------------------------------
    def _from_jsonld(self, page) -> list[Listing]:
        out: list[Listing] = []
        for script in page.query_selector_all('script[type="application/ld+json"]'):
            # NB: inner_text() returns "" for <script> (not visible) — use text_content().
            raw = script.text_content() or ""
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            for node in _walk(data):
                lst = self._listing_from_node(node)
                if lst:
                    out.append(lst)
        # de-dupe by url
        seen, uniq = set(), []
        for l in out:
            if l.url not in seen:
                seen.add(l.url)
                uniq.append(l)
        return uniq

    def _listing_from_node(self, node: dict) -> Listing | None:
        if not isinstance(node, dict):
            return None
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if not any(x in ("Car", "Vehicle", "Product", "Motorcycle") for x in types):
            return None
        name = node.get("name") or node.get("model")
        if not name or not isinstance(name, str):
            return None
        offers = node.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = _to_price(offers.get("price") if isinstance(offers, dict) else None)
        url = node.get("url") or (offers.get("url") if isinstance(offers, dict) else None) or ""
        if url and url.startswith("/"):
            url = self.base + url
        mileage = None
        odo = node.get("mileageFromOdometer")
        if isinstance(odo, dict):
            mileage = _to_int(odo.get("value"))
        elif odo is not None:
            mileage = _to_int(odo)
        if not url:
            return None
        return Listing(
            source=self.name, id=url.split("?")[0], title=name.strip(),
            price=price, mileage=mileage, url=url.split("?")[0],
        )

    # --- strategy 2: DOM link heuristic ------------------------------------
    def _from_links(self, page, config: Config) -> list[Listing]:
        selector = ", ".join(f"a[href*='{s}']" for s in self.DETAIL_SUBSTRS) or "a[href]"
        out: dict[str, Listing] = {}
        for a in page.query_selector_all(selector):
            href = (a.get_attribute("href") or "").split("?")[0]
            if not href:
                continue
            url = href if href.startswith("http") else self.base + href
            if url in out:
                continue
            # Grab the nearest ancestor that contains a price, else the link text.
            try:
                text = a.evaluate(
                    """el => { let n = el;
                        for (let i=0;i<6 && n;i++){ n=n.parentElement;
                          if(n && /\\$\\s?\\d/.test(n.innerText||'')) return n.innerText; }
                        return el.innerText || ''; }"""
                )
            except Exception:
                text = ""
            lst = self._parse_card_text(text, url)
            if lst:
                out[url] = lst
        return list(out.values())

    def _parse_card_text(self, text: str, url: str) -> Listing | None:
        if not text:
            return None
        price = None
        if m := PRICE_RE.search(text):
            price = _to_price(m.group(1))
        mileage = None
        if m := MILEAGE_RE.search(text):
            mileage = _to_int(m.group(1))
        # Title: first line containing a plausible model-year, else first real line.
        title = None
        for line in (l.strip() for l in text.splitlines() if l.strip()):
            if YEAR_RE.search(line) and len(line) < 80:
                title = line
                break
        if not title:
            title = next((l.strip() for l in text.splitlines() if l.strip()), None)
        if not title:
            return None
        return Listing(
            source=self.name, id=url, title=title, price=price, mileage=mileage, url=url,
        )


def _walk(data):
    """Yield every dict nested anywhere in a JSON structure."""
    if isinstance(data, dict):
        yield data
        for v in data.values():
            yield from _walk(v)
    elif isinstance(data, list):
        for v in data:
            yield from _walk(v)


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(v)) or 0) or None
    except (ValueError, TypeError):
        return None


def _to_price(v) -> int | None:
    """Parse a price that may carry decimals — '5995.00' -> 5995, not 599500."""
    if v is None:
        return None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None
