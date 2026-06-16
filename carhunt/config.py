"""Configuration loading and defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class Config:
    # --- search ---
    region: str = "sfbay"            # Craigslist region subdomain (e.g. sfbay, newyork, losangeles)
    max_price: int = 9000
    min_price: int = 0
    sources: list[str] = field(default_factory=lambda: ["craigslist"])

    # --- browser sources (facebook; cars.com is experimental) ---
    fb_city: str = "sanfrancisco"    # Facebook Marketplace city slug
    fb_scrolls: int = 40             # max scroll passes (stops early once no new cards appear)
    fb_max_listings: int = 150       # cap listings gathered from FB per run
    fb_session_dir: str = ".fb_session"  # persistent login profile (created by --fb-login)
    headed: bool = False             # show the real browser (needed to beat Cloudflare on cars.com)
    cars_zip: str = "94103"          # cars.com searches by ZIP
    cars_radius: int = 50            # cars.com search radius (miles)

    # --- buyer preferences (free text, fed verbatim into the scoring prompt) ---
    preferences: str = (
        "I'm a car enthusiast hunting for something cheap but actually cool and interesting — "
        "not a boring appliance. It must NOT be a money pit: favor models with a known-reliable "
        "reputation and avoid ones famous for expensive failures at this mileage. A convertible / "
        "roadster is a big plus. Cheaper is better, and lower mileage is better. I care about cheap "
        "running and insurance costs. Manual transmission is fine but not required."
    )

    # --- scoring ---
    model: str = "claude-opus-4-8"
    max_to_score: int = 60           # cap LLM calls per run (cost control)
    fetch_descriptions: bool = True  # pull detail-page text for richer scoring
    concurrency: int = 5
    min_overall_to_show: int = 0     # filter the final report
    serious_only: bool = True        # drop project/non-running/kit cars from results
    exclude_placeholder_prices: bool = True  # drop listings whose price is fake/placeholder
    min_realistic_price: int = 300   # local floor: skip obvious $1/$17 junk before scoring

    # --- output ---
    results_dir: str = "results"
    top_n_console: int = 20

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        data: dict[str, Any] = {}
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys in {p}: {sorted(unknown)}")
        return cls(**data)
