"""Shared console UI helpers (progress bars)."""

from __future__ import annotations

import contextlib
from typing import Callable, Iterator

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


@contextlib.contextmanager
def progress_bar(description: str, total: int) -> Iterator[Callable[[], None]]:
    """Context manager yielding an `advance()` callable for a single task bar."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        transient=False,
    ) as p:
        task = p.add_task(description, total=total)

        def advance() -> None:
            p.update(task, advance=1)

        yield advance
