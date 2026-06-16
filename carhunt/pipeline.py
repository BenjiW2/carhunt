"""Orchestrates scrape -> dedup -> prefilter -> enrich -> score -> rank."""

from __future__ import annotations

from .config import Config
from .models import Listing, ScoredListing
from .prioritize import interest_score
from .scoring import Scorer
from .scrapers import get_scraper


def scrape(config: Config) -> list[Listing]:
    all_listings: list[Listing] = []
    for source in config.sources:
        scraper = get_scraper(source)
        print(f"• scraping {source} ({config.region})…")
        try:
            found = scraper.search(config)
            print(f"  found {len(found)} listings")
            all_listings.append(found)  # type: ignore[arg-type]
        except NotImplementedError as e:
            print(f"  ⚠ {source} skipped: {e}")
        except Exception as e:  # noqa: BLE001 - one bad source shouldn't kill the run
            print(f"  ✗ {source} failed: {e}")
    # flatten
    return [lst for group in all_listings for lst in group]  # type: ignore[union-attr]


def dedup(listings: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    out: list[Listing] = []
    for lst in listings:
        k = lst.dedup_key()
        if k not in seen:
            seen.add(k)
            out.append(lst)
    return out


def prefilter(listings: list[Listing], config: Config) -> list[Listing]:
    """Cheap local filtering + prioritization before we spend tokens.

    We rank by a keyword-based interest score so the (capped) LLM budget targets
    likely-cool cars instead of whatever happens to be newest. Listings tie-break
    on input order, which the scraper already returns newest-first.
    """
    floor = max(config.min_price, config.min_realistic_price)
    kept = [
        lst
        for lst in listings
        if lst.price is not None and floor <= lst.price <= config.max_price
    ]
    ranked = sorted(kept, key=interest_score, reverse=True)
    return ranked[: config.max_to_score]


def enrich_descriptions(listings: list[Listing], config: Config) -> None:
    """Enrich detail data (descriptions, mileage) in place, per source.

    Each scraper decides how: Craigslist fetches detail pages over HTTP;
    Facebook drives the browser to read mileage off each item page.
    """
    if not config.fetch_descriptions:
        return
    by_source: dict[str, list[Listing]] = {}
    for lst in listings:
        by_source.setdefault(lst.source, []).append(lst)

    for source, group in by_source.items():
        get_scraper(source).enrich(group, config)


def run(config: Config) -> list[ScoredListing]:
    listings = scrape(config)
    listings = dedup(listings)
    print(f"• {len(listings)} unique listings after dedup")

    candidates = prefilter(listings, config)
    print(f"• scoring {len(candidates)} candidates (cap {config.max_to_score})")
    if not candidates:
        return []

    if config.fetch_descriptions:
        print("• fetching listing descriptions…")
        enrich_descriptions(candidates, config)

    print("• scoring with Claude…")
    scored = Scorer(config).score_all(candidates)

    # Drop what the buyer explicitly doesn't want: fake prices and non-serious cars.
    dropped_price = dropped_serious = 0
    kept: list[ScoredListing] = []
    for s in scored:
        if config.exclude_placeholder_prices and s.score.price_is_placeholder:
            dropped_price += 1
            continue
        if config.serious_only and not s.score.is_serious_car:
            dropped_serious += 1
            continue
        kept.append(s)
    if dropped_price or dropped_serious:
        print(
            f"• dropped {dropped_price} placeholder-price and "
            f"{dropped_serious} non-serious (project/kit/non-running) listings"
        )

    kept = [s for s in kept if s.score.overall >= config.min_overall_to_show]
    kept.sort(key=lambda s: s.score.overall, reverse=True)
    return kept
