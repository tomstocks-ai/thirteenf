"""Rendering: rich tables + raw JSON passthrough."""

from __future__ import annotations

import json
from typing import Any, Iterable

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def print_json(data: Any) -> None:
    """Print raw JSON (--json passthrough)."""
    console.print(json.dumps(data, indent=2, default=str))


def fmt_int(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def fmt_pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.1f}%"
    except (TypeError, ValueError):
        return str(value)


def fmt_usd_thousands(value: Any) -> str:
    """13F values are reported in $thousands; render as $ with separators."""
    if value is None:
        return "-"
    try:
        return f"${int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def trunc(value: Any, width: int) -> str:
    """Truncate long text with an ellipsis so tables stay readable."""
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def make_table(title: str, columns: Iterable[str]) -> Table:
    table = Table(title=title, title_justify="left")
    for col in columns:
        table.add_column(col, overflow="fold")
    return table


def render_table(title: str, columns: list[str], rows: Iterable[Iterable[Any]]) -> None:
    table = make_table(title, columns)
    for row in rows:
        table.add_row(*["" if cell is None else str(cell) for cell in row])
    console.print(table)
