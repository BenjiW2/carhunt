"""Craigslist scraper using the site's own JSON search API (no browser needed).

Craigslist's web UI calls https://sapi.craigslist.org/web/v8/postings/search/full
and renders the response client-side. We call the same endpoint directly. The
response packs each listing as an array of values that index into `decode`
dictionaries; the format below was reverse-engineered against live data:

    item = [
        idDelta,            # 0: postingId = decode.minPostingId + idDelta
        _sortDelta,         # 1: (internal sort key)
        _dateCode,          # 2: (internal)
        price,              # 3: int USD
        locField,           # 4: "1:<locIdx>~<lat>~<lon>"
        postCode,           # 5: image/post host code
        [13, extId],        # token sub-array
        [4, img, img, ...], # type 4: image codes ("3:<code>_<postcode>")
        [6, slug],          # type 6: URL slug
        [9, mileage],       # type 9: odometer (miles)  -- not always present
        [10, "$1,995"],     # type 10: formatted price
        title,              # last element: title string
    ]
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from ..config import Config
from ..models import Listing
from .base import Scraper, make_session

SAPI_URL = "https://sapi.craigslist.org/web/v8/postings/search/full"
IMG_URL = "https://images.craigslist.org/{code}_300x300.jpg"
PAGE_SIZE = 360  # Craigslist's hard cap per request


class CraigslistScraper(Scraper):
    name = "craigslist"

    def __init__(self) -> None:
        self.session = make_session()
        self._area_cache: dict[str, int] = {}

    # ------------------------------------------------------------------ areas
    def resolve_area_id(self, region: str) -> int:
        """Map a region subdomain (e.g. 'sfbay') to its numeric areaId.

        The reference API is gone, so we read the areaId out of the region's
        own search page bootstrap and cache it.
        """
        if region in self._area_cache:
            return self._area_cache[region]
        url = f"https://{region}.craigslist.org/search/cta"
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        m = re.search(r'"areaId"\s*:\s*(\d+)', r.text) or re.search(
            r'areaId["\']?\s*[:=]\s*["\']?(\d+)', r.text
        )
        if not m:
            raise RuntimeError(
                f"Could not resolve areaId for region '{region}'. "
                f"Is the region subdomain correct? (try sfbay, newyork, losangeles…)"
            )
        area_id = int(m.group(1))
        self._area_cache[region] = area_id
        return area_id

    # ----------------------------------------------------------------- search
    def search(self, config: Config) -> list[Listing]:
        area_id = self.resolve_area_id(config.region)
        params = {
            "batch": f"{area_id}-0-{PAGE_SIZE}-0-0",
            "cc": "US",
            "lang": "en",
            "searchPath": "cta",          # cars & trucks (owner + dealer)
            "sort": "date",
            "max_price": config.max_price,
        }
        if config.min_price:
            params["min_price"] = config.min_price

        r = self.session.get(SAPI_URL, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        data = payload.get("data", {})
        items = data.get("items", [])
        decode = data.get("decode", {})
        min_id = decode.get("minPostingId", 0)
        loc_desc = decode.get("locationDescriptions", [])
        host = (data.get("location") or {}).get("url", f"{config.region}.craigslist.org")

        listings: list[Listing] = []
        for raw in items:
            parsed = self._parse_item(raw, min_id, loc_desc, host)
            if parsed:
                listings.append(parsed)
        return listings

    def _parse_item(
        self, raw: list, min_id: int, loc_desc: list, host: str
    ) -> Listing | None:
        try:
            posting_id = min_id + raw[0]
            price = raw[3] if isinstance(raw[3], int) and raw[3] > 0 else None
            title = raw[-1] if isinstance(raw[-1], str) else ""
            if not title:
                return None

            slug = None
            mileage = None
            image_code = None
            for sub in raw[6:]:
                if isinstance(sub, list) and sub and isinstance(sub[0], int):
                    tag = sub[0]
                    if tag == 6 and len(sub) > 1:
                        slug = sub[1]
                    elif tag == 9 and len(sub) > 1 and isinstance(sub[1], int):
                        mileage = sub[1]
                    elif tag == 4 and len(sub) > 1 and image_code is None:
                        # "3:00S0S_dvCo268wuCu_0CI0t2" -> "00S0S_dvCo268wuCu"
                        first = sub[1]
                        m = re.match(r"\d+:([^_]+_[^_]+)_", first)
                        if m:
                            image_code = m.group(1)

            # location: "1:<locIdx>~<lat>~<lon>"
            location = lat = lon = None
            locf = raw[4] if len(raw) > 4 and isinstance(raw[4], str) else ""
            if ":" in locf:
                rest = locf.split(":", 1)[1]
                bits = rest.split("~")
                try:
                    loc_idx = int(bits[0])
                    if 0 <= loc_idx < len(loc_desc):
                        location = loc_desc[loc_idx]
                except (ValueError, IndexError):
                    pass
                if len(bits) >= 3:
                    try:
                        lat, lon = float(bits[1]), float(bits[2])
                    except ValueError:
                        pass

            url = f"https://{host}/cto/d/{slug}/{posting_id}.html" if slug else (
                f"https://{host}/cto/{posting_id}.html"
            )
            image_url = IMG_URL.format(code=image_code) if image_code else None

            return Listing(
                source=self.name,
                id=str(posting_id),
                title=title,
                price=price,
                mileage=mileage,
                location=location,
                lat=lat,
                lon=lon,
                url=url,
                image_url=image_url,
            )
        except (IndexError, TypeError, KeyError):
            return None

    # ------------------------------------------------------------ description
    def fetch_description(
        self, session: requests.Session, listing: Listing
    ) -> str | None:
        try:
            r = session.get(listing.url, timeout=20)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            body = soup.find(id="postingbody")
            if not body:
                return None
            text = body.get_text(" ", strip=True)
            # Drop the boilerplate prefix Craigslist injects.
            text = text.replace("QR Code Link to This Post", "").strip()
            return text[:1500] if text else None
        except requests.RequestException:
            return None
