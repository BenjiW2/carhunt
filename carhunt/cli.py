"""Command-line entrypoint: python -m carhunt [--config config.yaml] [overrides]."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from . import __version__
from .config import Config
from .pipeline import run
from .report import print_console, save


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="carhunt",
        description="Scrape used-car listings and rank them with Claude.",
    )
    p.add_argument("--config", help="Path to config.yaml (optional).")
    p.add_argument("--region", help="Craigslist region subdomain, e.g. sfbay, newyork.")
    p.add_argument("--max-price", type=int, help="Max price (USD).")
    p.add_argument("--min-price", type=int, help="Min price (USD).")
    p.add_argument("--max-to-score", type=int, help="Cap how many listings hit the LLM.")
    p.add_argument("--model", help="Claude model id (default claude-opus-4-8).")
    p.add_argument("--no-descriptions", action="store_true",
                   help="Skip fetching detail-page text (faster, less context for scoring).")
    p.add_argument("--sources", help="Comma-separated sources, e.g. craigslist,facebook.")
    p.add_argument("--fb-city", help="Facebook Marketplace city slug, e.g. sanfrancisco, newyork.")
    p.add_argument("--fb-login", action="store_true",
                   help="One-time: open a browser to log into Facebook (unlocks >24 listings), then exit.")
    p.add_argument("--headed", action="store_true",
                   help="Show the real browser window (needed to beat Cloudflare on cars.com).")
    p.add_argument("--min-score", type=int, help="Only show listings scoring >= this.")
    p.add_argument("--version", action="version", version=f"carhunt {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    # --fb-login is a setup step; it needs no API key and exits when done.
    if args.fb_login:
        try:
            config = Config.load(args.config)
        except (ValueError, OSError) as e:
            print(f"ERROR loading config: {e}", file=sys.stderr)
            return 2
        if args.fb_city:
            config.fb_city = args.fb_city
        from .scrapers import get_scraper
        get_scraper("facebook").login(config)  # type: ignore[attr-defined]
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Put it in a .env file (see .env.example) or export it.",
            file=sys.stderr,
        )
        return 2

    try:
        config = Config.load(args.config)
    except (ValueError, OSError) as e:
        print(f"ERROR loading config: {e}", file=sys.stderr)
        return 2

    # CLI overrides win over the config file.
    if args.region:
        config.region = args.region
    if args.max_price is not None:
        config.max_price = args.max_price
    if args.min_price is not None:
        config.min_price = args.min_price
    if args.max_to_score is not None:
        config.max_to_score = args.max_to_score
    if args.model:
        config.model = args.model
    if args.no_descriptions:
        config.fetch_descriptions = False
    if args.sources:
        config.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if args.fb_city:
        config.fb_city = args.fb_city
    if args.headed:
        config.headed = True
    if args.min_score is not None:
        config.min_overall_to_show = args.min_score

    scored = run(config)
    print_console(scored, config)
    if scored:
        json_path, md_path = save(scored, config)
        print(f"\nSaved: {md_path}\n       {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
