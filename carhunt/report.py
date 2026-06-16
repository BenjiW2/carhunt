"""Render ranked results to the console and to results/ files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import Config
from .models import ScoredListing


def _emoji(score: int) -> str:
    if score >= 80:
        return "🔥"
    if score >= 60:
        return "✅"
    if score >= 40:
        return "🤔"
    return "💤"


def print_console(scored: list[ScoredListing], config: Config) -> None:
    console = Console()
    if not scored:
        console.print("[yellow]No listings to show. Try raising max_price or max_to_score.[/]")
        return

    table = Table(title=f"Top cars — {config.region} (≤ ${config.max_price:,})", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="center")
    table.add_column("Car")
    table.add_column("Price", justify="right")
    table.add_column("Miles", justify="right")
    table.add_column("Verdict", max_width=48)

    for i, s in enumerate(scored[: config.top_n_console], 1):
        lst, sc = s.listing, s.score
        conv = " 🚗💨" if sc.is_convertible else ""
        price = f"${lst.price:,}" if lst.price else "—"
        miles = f"{lst.mileage:,}" if lst.mileage else "—"
        table.add_row(
            str(i),
            f"{_emoji(sc.overall)} {sc.overall}",
            f"{lst.title}{conv}",
            price,
            miles,
            sc.verdict,
        )
    console.print(table)
    console.print(
        "\n[dim]Sub-scores key: cool / reliability / value / running-cost. "
        "Full detail in the saved report.[/]"
    )

    # Show the top pick's full breakdown inline.
    top = scored[0]
    console.print(f"\n[bold]Top pick:[/] {top.listing.title}  [link={top.listing.url}]{top.listing.url}[/]")
    sc = top.score
    console.print(
        f"  cool {sc.cool_factor} · reliability {sc.reliability} · value {sc.value} · running-cost {sc.running_cost}"
    )
    console.print(f"  {sc.reasoning}")
    if sc.key_risks:
        console.print("  [red]Watch:[/] " + "; ".join(sc.key_risks))


def save(scored: list[ScoredListing], config: Config) -> tuple[Path, Path]:
    out_dir = Path(config.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"cars_{config.region}_{stamp}.json"
    md_path = out_dir / f"cars_{config.region}_{stamp}.md"

    json_path.write_text(
        json.dumps([s.model_dump() for s in scored], indent=2)
    )

    lines = [
        f"# Car hunt — {config.region} (≤ ${config.max_price:,})",
        f"_{datetime.now():%Y-%m-%d %H:%M}_ · {len(scored)} listings scored",
        "",
        f"**Buyer brief:** {config.preferences}",
        "",
    ]
    for i, s in enumerate(scored, 1):
        lst, sc = s.listing, s.score
        conv = " · convertible 🚗💨" if sc.is_convertible else ""
        price = f"${lst.price:,}" if lst.price else "—"
        miles = f"{lst.mileage:,} mi" if lst.mileage else "—"
        lines += [
            f"## {i}. {_emoji(sc.overall)} [{sc.overall}/100] {lst.title}{conv}",
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
            lines.append("**Watch:** " + "; ".join(sc.key_risks))
            lines.append("")
        lines.append(f"[View listing]({lst.url})")
        lines.append("")
    md_path.write_text("\n".join(lines))
    return json_path, md_path
