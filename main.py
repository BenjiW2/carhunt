#!/usr/bin/env python3
"""carhunt launcher — the easy front door.

Run this and it will, in order:
  1. create a local virtualenv and install everything (deps + headless Chromium),
  2. make sure your Claude API key is set,
  3. optionally log you into *your own* Facebook (for >24 listings),
  4. ask what kind of car you want (with a sensible default brief), and
  5. run the search and print the ranked results.

    python3 main.py            # interactive
    python3 main.py --default  # skip the questions, run the example search

Everything personal (API key, FB login, results) stays on your machine and is
gitignored — cloning this repo gives you the tool, not anyone else's secrets.
"""

from __future__ import annotations

# NOTE: only the standard library may be imported at module top-level — third-
# party packages aren't available until the bootstrap step below has installed
# them. App imports happen *inside* run(), after we're in the venv.
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
SENTINEL = VENV / ".carhunt_ready"


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _install() -> None:
    py = str(_venv_python())
    print("→ Installing Python dependencies (one-time)…")
    subprocess.check_call([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    print("→ Installing headless Chromium for browser scraping (one-time, ~150 MB)…")
    subprocess.check_call([py, "-m", "playwright", "install", "chromium"])


def _bootstrap() -> None:
    """Ensure a ready venv exists, then re-exec this script inside it."""
    in_venv = Path(sys.executable).resolve() == _venv_python().resolve()
    if in_venv:
        return
    if not VENV.exists():
        print("→ Creating virtual environment (.venv)…")
        venv.create(VENV, with_pip=True)
    if not SENTINEL.exists():
        _install()
        SENTINEL.write_text("ok\n")
    # Hand off to the venv's interpreter; everything after this runs there.
    os.execv(str(_venv_python()), [str(_venv_python()), str(ROOT / "main.py"), *sys.argv[1:]])


# ----------------------------------------------------------------- interactive

def _ask(prompt: str, default: str) -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def _ask_int(prompt: str, default: int) -> int:
    raw = _ask(prompt, str(default))
    try:
        return int(raw.replace("$", "").replace(",", ""))
    except ValueError:
        return default


def _ensure_api_key() -> bool:
    from dotenv import load_dotenv

    load_dotenv()
    if os.getenv("ANTHROPIC_API_KEY"):
        return True
    import getpass

    print("\nNo Claude API key found (needed to score cars).")
    key = getpass.getpass("Paste your ANTHROPIC_API_KEY (input hidden, Enter to abort): ").strip()
    if not key:
        return False
    os.environ["ANTHROPIC_API_KEY"] = key
    env = ROOT / ".env"
    if not env.exists():
        env.write_text(f"ANTHROPIC_API_KEY={key}\n")
        print("Saved to .env (gitignored).")
    return True


def run() -> int:
    _bootstrap()  # may re-exec; code below always runs inside the venv

    from carhunt.config import Config
    from carhunt.pipeline import run as run_pipeline
    from carhunt.report import print_console, save
    from carhunt.scrapers import get_scraper

    default_brief = Config().preferences
    use_default = "--default" in sys.argv or "-y" in sys.argv

    if not _ensure_api_key():
        print("Aborted: no API key.")
        return 2

    if use_default:
        cfg = Config(max_to_score=40, min_overall_to_show=50)
    else:
        print("\n=== What are you hunting for? (press Enter to accept each default) ===\n")
        region = _ask("Craigslist region (sfbay, newyork, losangeles, …)", "sfbay")
        max_price = _ask_int("Max price ($)", 9000)
        include_fb = _ask("Also search Facebook Marketplace? (y/n)", "n").lower().startswith("y")
        sources = ["craigslist"] + (["facebook"] if include_fb else [])
        fb_city = "sanfrancisco"
        if include_fb:
            fb_city = _ask("Facebook city slug (sanfrancisco, newyork, …)", "sanfrancisco")

        print("\nDescribe the kind of car you want — this is the brief Claude scores against.")
        print("Default example (a car-enthusiast's cheap-but-cool-and-reliable brief):\n")
        print("  " + default_brief + "\n")
        brief = input("Your brief (Enter to use the example): ").strip() or default_brief

        max_to_score = _ask_int("How many of the most-promising cars should Claude rate?", 40)
        min_score = _ask_int("Only show cars scoring at least…", 50)

        cfg = Config(
            region=region,
            fb_city=fb_city,
            max_price=max_price,
            sources=sources,
            preferences=brief,
            max_to_score=max_to_score,
            min_overall_to_show=min_score,
        )

    # Offer a one-time Facebook login if we'll scrape it and there's no session.
    if "facebook" in cfg.sources and not (ROOT / cfg.fb_session_dir / "Default").exists():
        if _ask(
            "\nNot logged into Facebook (anonymous tops out at ~24 listings). Log in now? (y/n)",
            "y",
        ).lower().startswith("y"):
            get_scraper("facebook").login(cfg)  # type: ignore[attr-defined]

    print()
    scored = run_pipeline(cfg)
    print_console(scored, cfg)
    if scored:
        json_path, md_path = save(scored, cfg)
        print(f"\nSaved: {md_path}\n       {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
