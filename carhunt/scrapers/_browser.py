"""Shared Playwright helpers for browser-driven scrapers.

Kept separate so the HTTP-only scrapers (Craigslist) never import Playwright.
Browser scrapers call `browser_context()` for a configured, somewhat-stealthy
context and `wait_past_challenge()` to sit through interstitial JS challenges
(e.g. Cloudflare's "Just a moment…").
"""

from __future__ import annotations

import contextlib
from typing import Iterator

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            "    pip install playwright && playwright install chromium"
        ) from e
    return sync_playwright


_STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
_CTX_OPTS = dict(
    user_agent=UA,
    viewport={"width": 1366, "height": 900},
    locale="en-US",
    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
)


@contextlib.contextmanager
def browser_context(headed: bool = False) -> Iterator:
    """Yield a ready-to-use Playwright page. Closes everything on exit."""
    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=_LAUNCH_ARGS)
        ctx = browser.new_context(**_CTX_OPTS)
        ctx.add_init_script(_STEALTH)
        page = ctx.new_page()
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                browser.close()


@contextlib.contextmanager
def persistent_context(user_data_dir: str, headed: bool = False) -> Iterator:
    """Yield a page from a persistent profile (cookies/login survive across runs).

    Used for Facebook: log in once in headed mode and the session is stored in
    `user_data_dir`, so subsequent runs are already authenticated.
    """
    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=not headed,
            args=_LAUNCH_ARGS,
            **_CTX_OPTS,
        )
        ctx.add_init_script(_STEALTH)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                ctx.close()


def wait_past_challenge(page, timeout_s: int = 25) -> bool:
    """Poll until an interstitial JS challenge clears. Returns True if it did."""
    for _ in range(timeout_s):
        title = (page.title() or "").lower()
        if "just a moment" not in title and "moment..." not in title:
            return True
        page.wait_for_timeout(1000)
    return False
