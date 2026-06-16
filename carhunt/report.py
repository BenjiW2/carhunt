"""Render ranked results to the console and to results/ files.

The console shows only the recommended cars (serious, real price, above the score
threshold). The saved Markdown/JSON contain EVERYTHING that was scored, grouped:
recommended first, then below-threshold, then flagged (placeholder / not-serious),
so you can see the full ranking and why anything was set aside.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import Config
from .models import Score, ScoredListing


def _emoji(score: int) -> str:
    if score >= 80:
        return "🔥"
    if score >= 60:
        return "✅"
    if score >= 40:
        return "🤔"
    return "💤"


def _flag(sc: Score, config: Config) -> str | None:
    """Why a listing isn't recommended (or None if it is eligible)."""
    if config.exclude_placeholder_prices and sc.price_is_placeholder:
        return "placeholder price"
    if config.serious_only and not sc.is_serious_car:
        return "not a serious car (project/non-running/kit)"
    return None


def _bucket(scored: list[ScoredListing], config: Config):
    recommended, below, flagged = [], [], []
    for s in scored:
        reason = _flag(s.score, config)
        if reason is not None:
            flagged.append((s, reason))
        elif s.score.overall < config.min_overall_to_show:
            below.append(s)
        else:
            recommended.append(s)
    return recommended, below, flagged


def print_console(scored: list[ScoredListing], config: Config) -> None:
    console = Console()
    recommended, below, flagged = _bucket(scored, config)

    if not recommended:
        console.print(
            "[yellow]No recommended cars cleared the filters this run.[/] "
            f"({len(below)} scored below {config.min_overall_to_show}, "
            f"{len(flagged)} flagged.) Full ranking saved to the report."
        )
        if not scored:
            return

    table = Table(title=f"Top cars — {config.region} (≤ ${config.max_price:,})", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="center")
    table.add_column("Car")
    table.add_column("Price", justify="right")
    table.add_column("Miles", justify="right")
    table.add_column("Verdict", max_width=48)

    for i, s in enumerate(recommended[: config.top_n_console], 1):
        lst, sc = s.listing, s.score
        conv = " 🚗💨" if sc.is_convertible else ""
        src = {"craigslist": "CL", "facebook": "FB", "carscom": "CC"}.get(lst.source, lst.source[:2])
        table.add_row(
            str(i),
            f"{_emoji(sc.overall)} {sc.overall}",
            f"[dim]{src}[/] {lst.title}{conv}",
            f"${lst.price:,}" if lst.price else "—",
            f"{lst.mileage:,}" if lst.mileage else "—",
            sc.verdict,
        )
    console.print(table)
    console.print(
        f"\n[dim]Showing {min(len(recommended), config.top_n_console)} of {len(recommended)} "
        f"recommended · {len(below)} below threshold · {len(flagged)} flagged — "
        "full ranking in the saved report.[/]"
    )

    if recommended:
        top = recommended[0]
        sc = top.score
        console.print(f"\n[bold]Top pick:[/] {top.listing.title}  [link={top.listing.url}]{top.listing.url}[/]")
        console.print(
            f"  cool {sc.cool_factor} · reliability {sc.reliability} · value {sc.value} · running-cost {sc.running_cost}"
        )
        console.print(f"  {sc.reasoning}")
        if sc.key_risks:
            console.print("  [red]Watch:[/] " + "; ".join(sc.key_risks))


def _full_block(i: int, s: ScoredListing) -> list[str]:
    lst, sc = s.listing, s.score
    conv = " · convertible 🚗💨" if sc.is_convertible else ""
    price = f"${lst.price:,}" if lst.price else "—"
    miles = f"{lst.mileage:,} mi" if lst.mileage else "—"
    lines = [
        f"### {i}. {_emoji(sc.overall)} [{sc.overall}/100] {lst.title}{conv}  ·  _{lst.source}_",
        f"**{price}** · {miles} · {lst.location or '—'}  ",
        f"cool **{sc.cool_factor}** · reliability **{sc.reliability}** · "
        f"value **{sc.value}** · running-cost **{sc.running_cost}**  ",
        "",
        f"> {sc.verdict}",
        "",
        sc.reasoning,
        "",
    ]
    if sc.key_risks:
        lines += ["**Watch:** " + "; ".join(sc.key_risks), ""]
    lines += [f"[View listing]({lst.url})", ""]
    return lines


def _compact_line(s: ScoredListing, note: str = "") -> str:
    lst, sc = s.listing, s.score
    price = f"${lst.price:,}" if lst.price else "—"
    miles = f"{lst.mileage:,}mi" if lst.mileage else "—"
    extra = f" — _{note}_" if note else ""
    return (
        f"- **{sc.overall}** · [{lst.title}]({lst.url}) · {price} · {miles} · "
        f"_{lst.source}_{extra}  \n  {sc.verdict}"
    )


def save(scored: list[ScoredListing], config: Config) -> tuple[Path, Path]:
    out_dir = Path(config.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"cars_{config.region}_{stamp}.json"
    md_path = out_dir / f"cars_{config.region}_{stamp}.md"

    recommended, below, flagged = _bucket(scored, config)

    # JSON: everything, each tagged with its status.
    payload = []
    for s in scored:
        reason = _flag(s.score, config)
        status = (
            "flagged" if reason
            else "below_threshold" if s.score.overall < config.min_overall_to_show
            else "recommended"
        )
        payload.append({"status": status, "flag_reason": reason, **s.model_dump()})
    json_path.write_text(json.dumps(payload, indent=2))

    # Markdown: full ranking, sectioned.
    lines = [
        f"# Car hunt — {config.region} (≤ ${config.max_price:,})",
        f"_{datetime.now():%Y-%m-%d %H:%M}_ · {len(scored)} cars scored "
        f"({len(recommended)} recommended · {len(below)} below threshold · {len(flagged)} flagged)",
        "",
        f"**Buyer brief:** {config.preferences}",
        "",
        f"## ✅ Recommended ({len(recommended)})",
        "",
    ]
    if recommended:
        for i, s in enumerate(recommended, 1):
            lines += _full_block(i, s)
    else:
        lines += ["_None cleared the filters this run._", ""]

    if below:
        lines += [
            f"## 🔻 Below the score threshold (< {config.min_overall_to_show}) — {len(below)}",
            "_Scored, serious, real price — just didn't rate high enough._",
            "",
        ]
        lines += [_compact_line(s) for s in below]
        lines.append("")

    if flagged:
        lines += [
            f"## ⚠️ Flagged — set aside ({len(flagged)})",
            "_Placeholder prices or not-a-serious-car (project / non-running / kit)._",
            "",
        ]
        lines += [_compact_line(s, note) for s, note in flagged]
        lines.append("")

    md_path.write_text("\n".join(lines))
    return json_path, md_path
