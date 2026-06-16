"""Core data models shared across scrapers, scoring, and reporting."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field


class Listing(BaseModel):
    """A normalized vehicle listing from any source."""

    source: str                      # "craigslist", "facebook", "autotrader"
    id: str                          # source-unique id
    title: str
    price: Optional[int] = None      # USD
    mileage: Optional[int] = None    # miles
    year: Optional[int] = None
    location: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    url: str
    image_url: Optional[str] = None
    description: Optional[str] = None

    def dedup_key(self) -> str:
        """Loose key for cross-source de-duplication."""
        t = re.sub(r"[^a-z0-9]", "", self.title.lower())
        return f"{t}:{self.price or 0}:{self.mileage or 0}"

    def guess_year(self) -> Optional[int]:
        if self.year:
            return self.year
        m = re.search(r"\b(19[6-9]\d|20[0-4]\d)\b", self.title)
        return int(m.group(1)) if m else None


class Score(BaseModel):
    """Claude's structured judgement of a single listing.

    All sub-scores are 0-100 (higher is better). The prompt defines what each
    one means; we keep them as plain ints because structured outputs don't
    enforce numeric bounds (the model is instructed to stay in range).
    """

    is_serious_car: bool = Field(description="True ONLY if this is a complete, running, road-ready car the buyer could drive home and rely on. False for project/restoration cars, non-running cars, anything needing an engine/transmission rebuild, kit cars / replicas / dune buggies / custom one-offs, parts cars, or salvage that isn't roadworthy.")
    price_is_placeholder: bool = Field(description="True if the listed price is clearly fake/placeholder/scam — e.g. $1, $123, or a figure far below plausible value, OR the description reveals the real asking price is much higher.")
    overall: int = Field(description="0-100 overall fit for THIS buyer. Anchor: 80+ = chase it today, 60-79 = solid, 40-59 = meh, <40 = skip. A car that is not serious (project/non-running/kit) or has a placeholder price must score below 25.")
    cool_factor: int = Field(description="0-100 how interesting/desirable to a car enthusiast.")
    reliability: int = Field(description="0-100 likelihood it runs well and won't become a money pit, given the model's reputation AND its current condition. If the car needs rebuilding, isn't running, or needs major mechanical work (engine/transmission/restoration), this is 0-10. A flaky failing component (e.g. gearbox won't engage a gear) is 0-15.")
    value: int = Field(description="0-100 price-and-mileage value. Cheaper for what you get scores higher. If price_is_placeholder, set this to 0.")
    running_cost: int = Field(description="0-100 cheapness to insure/fuel/maintain (100 = very cheap to run).")
    is_convertible: bool = Field(description="True if this is a convertible / roadster / targa.")
    recommended: bool = Field(description="True only if this is a serious, road-ready car with a real price that's worth the buyer contacting the seller.")
    verdict: str = Field(description="One punchy sentence the buyer reads first.")
    reasoning: str = Field(description="2-4 sentences: why this score, what's cool, reliability/condition notes tied to the specific model.")
    key_risks: list[str] = Field(description="Specific things to check or worry about (e.g. 'BMW N47 timing chain', 'rust on rockers', 'salvage title'). Empty if genuinely low-risk.")


class ScoredListing(BaseModel):
    listing: Listing
    score: Score
