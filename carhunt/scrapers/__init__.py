"""Pluggable listing scrapers."""

from __future__ import annotations

from .base import Scraper
from .craigslist import CraigslistScraper
from .facebook import FacebookScraper
from .carscom import CarsComScraper
from .autotrader import AutoTraderScraper
from .cargurus import CarGurusScraper

REGISTRY: dict[str, type[Scraper]] = {
    "craigslist": CraigslistScraper,
    "facebook": FacebookScraper,
    "carscom": CarsComScraper,
    "autotrader": AutoTraderScraper,
    "cargurus": CarGurusScraper,
}


def get_scraper(name: str) -> Scraper:
    try:
        return REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown source '{name}'. Available: {sorted(REGISTRY)}"
        ) from None
