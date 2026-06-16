"""Cheap, local pre-ranking to spend the LLM budget on promising candidates.

Scoring the *newest* N listings buries the interesting cars — convertibles and
enthusiast models are scattered across the whole result set, not concentrated in
the latest dozen. This module assigns each listing a fast, keyword-based
"interest" score (no API calls) so the pipeline can rank candidates and feed the
most promising ones to Claude first. The LLM still makes the real call; this just
decides *who gets scored* when there's a budget cap.
"""

from __future__ import annotations

import re

from .models import Listing

# Body styles the buyer explicitly favors — weighted highest.
CONVERTIBLE_TERMS = [
    "convertible", "roadster", "cabriolet", "cabrio", "drop top", "droptop",
    "soft top", "softtop", "spider", "spyder", "targa",
]

# Models/badges with genuine enthusiast appeal that turn up cheap. Each is a
# whole-word match; weights are rough "how cool / how much should this jump the
# queue" values.
INTEREST_TERMS: dict[str, float] = {
    # roadsters & sports cars (also often convertibles)
    "miata": 6, "mx-5": 6, "mx5": 6, "s2000": 6, "boxster": 5, "cayman": 5,
    "z3": 5, "z4": 5, "slk": 4, "tt": 4, "solstice": 4, "sky": 3, "crossfire": 4,
    "mr2": 5, "mr-2": 5, "spitfire": 5, "miata": 6, "fiat 124": 5, "abarth": 4,
    # coupes / hot hatches / fun
    "brz": 5, "gt86": 5, "fr-s": 5, "frs": 4, "86": 3, "supra": 6, "rx-7": 6,
    "rx7": 6, "rx-8": 4, "rx8": 4, "350z": 5, "370z": 5, "240sx": 5, "celica": 4,
    "integra": 5, "rsx": 4, "prelude": 4, "del sol": 5, "civic si": 5, "si": 2,
    "type r": 6, "gti": 4, "golf r": 5, "wrx": 5, "sti": 6, "evo": 6, "mini": 3,
    "cooper s": 4, "mustang": 4, "camaro": 4, "corvette": 6, "firebird": 4,
    "trans am": 5, "challenger": 4, "charger": 3, "nsx": 7, "viper": 7,
    # characterful classics / oddballs
    "alfa": 5, "jaguar": 4, "porsche": 5, "datsun": 6, "e30": 6, "e36": 4,
    "e46": 4, "m3": 6, "m5": 6, "911": 6, "beetle": 3, "karmann": 6, "bronco": 4,
    "fj": 4, "land cruiser": 5, "4runner": 3, "tacoma": 2, "wrangler": 3,
}


def _word_re(term: str) -> re.Pattern[str]:
    # Word-ish boundaries so "si" doesn't match "sierra"; allow hyphens/spaces.
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")


_CONV_RES = [(_word_re(t)) for t in CONVERTIBLE_TERMS]
_INT_RES = [(_word_re(t), w) for t, w in INTEREST_TERMS.items()]


def interest_score(listing: Listing) -> float:
    """Higher = more likely to be worth an LLM look. Pure heuristic."""
    title = listing.title.lower()
    score = 0.0

    if any(r.search(title) for r in _CONV_RES):
        score += 8  # convertible is the buyer's headline preference

    # Best single model match (don't stack a dozen partials).
    best = 0.0
    for rx, w in _INT_RES:
        if rx.search(title) and w > best:
            best = w
    score += best

    # Mild nudge toward cheaper cars (the brief says cheaper is better), but
    # small so it never outranks a genuinely cool find.
    if listing.price:
        score += max(0.0, (9000 - listing.price) / 9000) * 1.5

    return score
