"""Score listings against the buyer's preferences using the Claude API.

Each listing is scored independently with a shared, cached system prompt so the
model's car knowledge ("which cheap convertibles are bulletproof vs money pits")
does the heavy lifting. We use structured outputs (`messages.parse`) so every
response validates against the Score schema — no brittle text parsing.
"""

from __future__ import annotations

import concurrent.futures
from typing import Optional

import anthropic

from .config import Config
from .models import Listing, Score, ScoredListing
from .ui import progress_bar

SYSTEM_PROMPT = """You are an expert used-car buyer's assistant and a genuine car enthusiast \
with deep, specific knowledge of model reliability, common failure points, running costs, \
and what makes a car interesting. You are evaluating individual US used-car listings for one \
specific buyer.

The buyer's brief:
{preferences}

THE BUYER NEEDS A SERIOUS, USABLE CAR — one they can drive home today and rely on. This is \
the most important filter. Be ruthless about it:
- is_serious_car is FALSE for: project/restoration cars, anything "needs work" / "not running" / \
"needs engine or transmission rebuild" / "mechanic special", kit cars, replicas, dune buggies, \
custom one-offs and home-built specials, parts cars, and salvage that isn't roadworthy. These \
are NOT what the buyer wants no matter how cool — score overall below 25.
- is_serious_car is TRUE only for complete, running, road-ready cars.

How to score (every numeric field is 0-100, higher is better):
- cool_factor: Would an enthusiast actually want this? Reward interesting, characterful, \
fun-to-drive cars (e.g. Miata/MX-5, BMW Z3/Z4, Boxster, MR2, S2000, old Mustangs, \
Mercedes SLK, factory roadsters). Penalize generic appliances (base econoboxes, beige \
sedans) unless there's something genuinely notable.
- reliability: Use the SPECIFIC model's real-world reputation AND the car's CURRENT condition. \
Reward known-bulletproof drivetrains. CRITICAL: if the car needs rebuilding, isn't running, or \
needs major mechanical work (engine, transmission, full restoration), reliability is 0-10 — a \
car you have to rebuild is not reliable. A specific failing component (e.g. "transmission won't \
engage 4th") is 0-15. Otherwise penalize models notorious for expensive failures (e.g. early \
BMW N47 timing chains, R56 Mini timing-chain/turbo issues, VW/Audi DSG and carbon issues, \
Range Rover air suspension/electronics, older German electrical gremlins, CVT-prone models, \
head-gasket-prone engines). Be concrete in key_risks.
- value: Is the price good for the car, year, and mileage? Cheaper-for-what-you-get scores \
higher. A clean low-mile example at a fair price beats a tired one that's only slightly cheaper.
- running_cost: Cheapness to insure, fuel, and maintain. Small reliable engines and cars with \
cheap, available parts score high; thirsty V8s, exotic/German parts, and high-insurance-group \
cars score lower.
- is_convertible: true for convertibles, roadsters, cabriolets, targas, spiders.
- recommended: true only if you'd tell this specific buyer it's worth contacting the seller.
- overall: Your holistic judgement for THIS buyer, weighting their brief. A convertible is a \
plus. Money-pit risk should pull this down hard even if the car is cool. Anchors: 80+ = chase \
it today; 60-79 = solid candidate; 40-59 = mediocre; below 40 = skip.

Watch for traps: an implausibly low price (e.g. $1, $17, a few hundred dollars for a late-model \
car) is almost always a placeholder, typo, or scam — the real figure is often buried in the title \
or description. Set price_is_placeholder=true for these, set value=0, and keep overall below 25.

Be decisive and specific. Tie reliability and risks to the actual make/model/engine when you \
recognize it. If a listing is too vague to judge (no model identifiable), score conservatively \
and say so. Keep verdict to one punchy sentence."""


def _format_listing(listing: Listing) -> str:
    parts = [f"Title: {listing.title}"]
    parts.append(f"Price: ${listing.price:,}" if listing.price else "Price: (not listed)")
    if listing.mileage:
        parts.append(f"Mileage: {listing.mileage:,} miles")
    if listing.guess_year():
        parts.append(f"Year (from title): {listing.guess_year()}")
    if listing.location:
        parts.append(f"Location: {listing.location}")
    if listing.description:
        parts.append(f"Seller description:\n{listing.description}")
    return "\n".join(parts)


class Scorer:
    def __init__(self, config: Config):
        self.config = config
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.system = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.format(preferences=config.preferences),
                "cache_control": {"type": "ephemeral"},  # shared across all listings
            }
        ]

    def score_one(self, listing: Listing) -> Optional[ScoredListing]:
        user = (
            "Score this used-car listing for the buyer described in your instructions.\n\n"
            + _format_listing(listing)
        )
        try:
            resp = self.client.messages.parse(
                model=self.config.model,
                max_tokens=1200,
                system=self.system,
                output_config={"effort": "low"},  # cheap, fast; the judgement is small
                messages=[{"role": "user", "content": user}],
                output_format=Score,
            )
        except anthropic.APIError as e:
            print(f"  ! scoring failed for {listing.id}: {e}")
            return None
        score = resp.parsed_output
        if score is None:
            return None
        return ScoredListing(listing=listing, score=score)

    def score_all(self, listings: list[Listing]) -> list[ScoredListing]:
        """Score listings concurrently. Order of results is not guaranteed; the
        pipeline sorts afterwards."""
        results: list[ScoredListing] = []
        with progress_bar("  scoring with Claude", len(listings)) as advance:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.concurrency) as ex:
                futures = {ex.submit(self.score_one, lst): lst for lst in listings}
                for fut in concurrent.futures.as_completed(futures):
                    scored = fut.result()
                    if scored:
                        results.append(scored)
                    advance()
        return results
