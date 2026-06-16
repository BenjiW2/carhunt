"""Shared Playwright helpers for browser-driven scrapers.

Kept separate so the HTTP-only scrapers (Craigslist) never import Playwright.
Browser scrapers call `browser_context()` for a configured, somewhat-stealthy
context and `wait_past_challenge()` to sit through interstitial JS challenges
(e.g. Cloudflare's "Just a moment…").
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Real consumer browsers beat Cloudflare/PerimeterX where bundled Chromium loops
# the "verify you're human" challenge. We try Playwright channels first, then
# known real-browser executables (macOS paths), then fall back to bundled.
_REAL_BROWSER_EXES = [
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def _launch_real_chromium(p, headless: bool, args: list[str]):
    """Launch the most realistic Chromium-family browser available."""
    for channel in ("chrome", "msedge"):
        try:
            return p.chromium.launch(headless=headless, channel=channel, args=args)
        except Exception:
            continue
    for exe in _REAL_BROWSER_EXES:
        if os.path.exists(exe):
            try:
                return p.chromium.launch(headless=headless, executable_path=exe, args=args)
            except Exception:
                continue
    return p.chromium.launch(headless=headless, args=args)  # bundled Chromium


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
    """Yield a ready-to-use Playwright page. Closes everything on exit.

    Prefers the *real* installed Google Chrome (`channel="chrome"`) over
    Playwright's bundled Chromium — Cloudflare/PerimeterX fingerprint the bundled
    build and loop the "verify you're human" challenge on it. Falls back to
    bundled Chromium if Chrome isn't installed.
    """
    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser = _launch_real_chromium(p, not headed, _LAUNCH_ARGS)
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


# Cookie/consent banners (OneTrust, TrustArc, generic) overlay the page and stop
# listings from rendering/being found until dismissed.
_CONSENT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#truste-consent-button",
    "button#gdpr-consent-accept",
    "[data-testid='accept-cookie-banner']",
    "[aria-label='Accept all']",
    "[aria-label='Accept All']",
]
_CONSENT_TEXTS = ["Accept all", "Accept All", "Accept Cookies", "Accept", "I Accept", "Agree", "Got it"]


_BLOCK_MARKERS = (
    "currently unavailable", "incident number", "access denied",
    "request unsuccessful", "pardon our interruption", "unusual traffic",
    "you have been blocked", "reference id",
)


def looks_blocked(page) -> bool:
    """Detect a bot-block / 'site unavailable' interstitial (Akamai/PerimeterX/etc.)."""
    try:
        blob = ((page.title() or "") + " " + (page.inner_text("body") or "")[:2000]).lower()
    except Exception:
        return False
    return any(m in blob for m in _BLOCK_MARKERS)


def dismiss_consent(page) -> bool:
    """Best-effort click of a cookie/consent 'Accept' button. Returns True if clicked."""
    import contextlib as _c

    for sel in _CONSENT_SELECTORS:
        with _c.suppress(Exception):
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(timeout=2500)
                page.wait_for_timeout(700)
                return True
    for label in _CONSENT_TEXTS:
        with _c.suppress(Exception):
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(700)
                return True
    return False
