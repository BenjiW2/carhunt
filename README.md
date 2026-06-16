# carhunt 🚗💨

A used-car hunter that scrapes listings and ranks them with Claude against *your*
taste — in this case: **cheap, but actually cool, reliable, and ideally a convertible.**

It scrapes Craigslist over its own JSON API (no browser, no login), pulls each
listing's price/mileage/description, then asks Claude to score every car on
**cool-factor, reliability, value, and running cost** using its built-in knowledge
of which cheap cars are bulletproof versus which are money pits. Output is a ranked
table plus a saved Markdown + JSON report.

```
🔥 84  1999 Mazda MX-5 Miata 🚗💨   $6,500   118k mi   "Bulletproof, cheap to run, and the most fun-per-dollar roadster on the list."
✅ 71  2007 Subaru Forester 5MT      $6,500   152k mi   "Practical, reliable boxer, manual is a plus — just not exciting."
💤 31  2010 Range Rover Sport HSE    $1,200   250k mi   "Money pit. Air suspension + electronics at 250k = a project, not a car."
```

## Sources

| Source | How | Status |
|---|---|---|
| **Craigslist** | HTTP JSON API (`sapi.craigslist.org`) | ✅ Reliable. Includes private sellers **and dealers**. ~360 listings/region. |
| **Facebook Marketplace** | Playwright | ✅ Works. Anonymous = ~24 listings/run; **log in once to unlock 150+** (see below). No mileage in the grid. |
| **Cars.com** | Playwright dealer inventory | ⚠️ Experimental. Behind Cloudflare — clears only intermittently headless; **run `--headed`** on your own machine for reliability. Fails safe (skips) if blocked. |
| **CarGurus / AutoTrader / TrueCar** | — | ❌ Hard Cloudflare/bot walls; not viable over HTTP or headless. Would need headed mode + stealth tooling or a paid scraping API. |

Enable sources with `--sources` or the `sources:` list in `config.yaml`:

```bash
python -m carhunt --sources craigslist,facebook --fb-city sanfrancisco
python -m carhunt --sources craigslist,facebook,carscom --headed   # cars.com needs headed
```

> **Browser sources need a one-time setup:** `pip install playwright && playwright install chromium`.

### Facebook Marketplace login (unlocks 150+ listings)

Anonymous browsing caps at ~24 listings. Log in **once** to lift that — your
session is saved to `.fb_session/` (gitignored) and reused on every later run:

```bash
python -m carhunt --fb-login
```

This opens a real browser window; log in by hand (the script never sees your
password), then press Enter in the terminal. After that:

```bash
python -m carhunt --sources craigslist,facebook --max-to-score 60
```

If the session expires, just run `--fb-login` again.

## Quick start (one command)

```bash
python3 main.py
```

`main.py` is the easy front door. On first run it creates a local virtualenv,
installs everything (deps + headless Chromium), checks for your Claude API key,
optionally logs you into **your own** Facebook, then asks what car you want
(press Enter to accept the example enthusiast brief) and runs the search.

```bash
python3 main.py --default   # skip the questions, run the example search
```

Everything personal — your API key, your Facebook login, your results — stays on
your machine and is gitignored. Cloning this repo gives you the tool, not anyone
else's secrets.

## Manual setup (if you'd rather not use main.py)

```bash
cd "fbm scraper"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium    # only needed for facebook / cars.com

cp .env.example .env          # then put your Claude API key in it
cp config.example.yaml config.yaml   # optional — defaults work out of the box
```

Your key goes in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

> **VS Code note:** if the editor flags `import anthropic`, point it at the venv
> interpreter (`Cmd-Shift-P → Python: Select Interpreter → ./.venv`). The code runs
> fine regardless.

## Run

```bash
# Uses config.yaml (or built-in defaults): sfbay, ≤ $9,000
python -m carhunt

# Override anything from the CLI:
python -m carhunt --region losangeles --max-price 6000
python -m carhunt --region newyork --max-to-score 30 --min-score 55
python -m carhunt --model claude-haiku-4-5      # cheaper bulk scoring
python -m carhunt --no-descriptions             # faster, less context for scoring
```

Results print to the console and save to `results/cars_<region>_<timestamp>.md` and `.json`.

### Finding your region

`--region` is the Craigslist subdomain for your city — the bit before
`.craigslist.org`. Examples: `sfbay`, `losangeles`, `sandiego`, `newyork`,
`chicago`, `seattle`, `boston`, `sacramento`, `portland`, `denver`. The areaId is
resolved automatically.

## How scoring works

Every candidate listing is sent to Claude with a shared, cached system prompt that
encodes your buyer brief (edit `preferences` in `config.yaml`). Claude returns a
structured judgement per car:

| Field | Meaning (0–100) |
|---|---|
| `overall` | Holistic fit for you — 80+ chase it, 60–79 solid, 40–59 meh, <40 skip |
| `cool_factor` | How interesting/desirable to an enthusiast |
| `reliability` | Won't-be-a-money-pit, given the model's reputation **at that mileage** |
| `value` | Price-and-mileage value |
| `running_cost` | Cheapness to insure/fuel/maintain |

Plus `is_convertible`, `recommended`, a one-line `verdict`, `reasoning`, and
specific `key_risks` (e.g. "BMW N47 timing chain", "Range Rover air suspension").

**Serious cars only (on by default).** The pipeline drops listings the buyer
can't actually use:
- `serious_only` — cuts project/restoration cars, non-running cars, anything
  needing an engine/transmission rebuild, kit cars/replicas, and parts cars.
  A car that needs rebuilding scores ~0 on reliability.
- `exclude_placeholder_prices` — cuts fake/placeholder prices ($1, "$816 C8
  Corvette", a real ask hidden in the description).
- `min_realistic_price` — local floor that skips obvious $1/$17 junk before it
  even costs a token.

Set any to `false` in `config.yaml` to see everything.

### Cost & tuning

- `max_to_score` caps how many listings hit the API per run (default 60) — the main
  cost lever. A run of 60 on `claude-opus-4-8` is well under ~$1 thanks to prompt
  caching on the system prompt.
- Switch `model` to `claude-sonnet-4-6` or `claude-haiku-4-5` for cheaper bulk runs.
- `min_overall_to_show` / `--min-score` trims the report to good matches only.

## Project layout

```
carhunt/
  cli.py            # entrypoint (python -m carhunt)
  config.py         # config + defaults
  models.py         # Listing, Score, ScoredListing (pydantic)
  pipeline.py       # scrape → dedup → prefilter → enrich → score → rank
  scoring.py        # Claude scoring (structured outputs, cached prompt)
  report.py         # rich console table + markdown/json output
  scrapers/
    base.py         # Scraper interface + HTTP session
    craigslist.py   # working: Craigslist JSON API + detail descriptions
    facebook.py     # stub for the browser phase
    autotrader.py   # stub for the browser phase
```

## Roadmap

- Playwright phase: log into Facebook Marketplace, drive AutoTrader/Cars.com.
- Pagination beyond the first 360 Craigslist results per region.
- Multi-region sweeps and de-duplication across nearby areas.
- Optional Batch API scoring (50% cheaper) for large runs.
```
