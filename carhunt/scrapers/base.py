"""Scraper interface + a shared HTTP session."""

from __future__ import annotations

import concurrent.futures
from abc import ABC, abstractmethod

import requests

from ..config import Config
from ..models import Listing
from ..ui import progress_bar

# A realistic desktop UA. Craigslist serves its JSON API to this happily.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


class Scraper(ABC):
    """Base class for a listing source."""

    name: str = "base"

    @abstractmethod
    def search(self, config: Config) -> list[Listing]:
        """Return listings matching the config's search criteria.

        Implementations should be polite (timeouts, no hammering) and must not
        raise on an empty result — return [] and let the pipeline carry on.
        """

    def fetch_description(self, session: requests.Session, listing: Listing) -> str | None:
        """Optionally enrich one listing with detail-page text. Default: nothing."""
        return None

    def enrich(self, listings: list[Listing], config: Config) -> None:
        """Enrich a batch of listings in place (mileage, description, …).

        Default implementation fetches detail-page text over HTTP concurrently via
        `fetch_description`. Browser-driven sources (e.g. Facebook) override this
        to drive a real browser instead.
        """
        session = make_session()
        with progress_bar(f"  {self.name}: detail pages", len(listings)) as advance:
            with concurrent.futures.ThreadPoolExecutor(max_workers=config.concurrency) as ex:
                futures = {ex.submit(self.fetch_description, session, l): l for l in listings}
                for fut in concurrent.futures.as_completed(futures):
                    lst = futures[fut]
                    try:
                        lst.description = fut.result()
                    except Exception:  # noqa: BLE001
                        lst.description = None
                    advance()
