"""cyclopts App and command definitions for thirteenf."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Optional

from cyclopts import App, Parameter
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from thirteenf.client import EDGAR_BASE, THIRTEENF_BASE, FetchError, get_json
from thirteenf.quotes import get_quote
from thirteenf.render import (
    console,
    err_console,
    fmt_int,
    fmt_pct,
    fmt_usd,
    fmt_usd_thousands,
    print_json,
    render_table,
    trunc,
)
from thirteenf.watchlist import WATCHLIST

app = App(name="13f", help="13F holdings data from 13f.info and SEC EDGAR.")

JsonFlag = Annotated[bool, Parameter(name="--json", help="Print raw JSON instead of rich tables.")]
NoCacheFlag = Annotated[bool, Parameter(name="--no-cache", help="Bypass cache reads (still writes).")]
LimitOpt = Annotated[Optional[int], Parameter(name="--limit", help="Max rows to display.")]
OnlyOpt = Annotated[
    Optional[list[str]],
    Parameter(
        name="--only",
        help="Show only these position groups (repeatable): new, increased, reduced, closed.",
    ),
]


def _run(fn, *args, **kwargs) -> None:
    """Execute a command body, converting FetchError into a clean exit."""
    try:
        fn(*args, **kwargs)
    except FetchError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from None


def _external_id(value: str) -> str:
    """Normalize an accession number / external id (strip dashes)."""
    return value.replace("-", "").strip()


def _manager_cik(url: str) -> str:
    # "/manager/0000895421-morgan-stanley" -> "0000895421"
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.split("-", 1)[0]


def _resolve_symbol(cusip: str, issuer: str | None = None, *, no_cache: bool = False) -> Optional[str]:
    """Recover a ticker symbol for a CUSIP via 13f.info autocomplete.

    Queries by issuer name first (falling back to the CUSIP itself) and picks
    the autocomplete hit whose URL ends in the CUSIP.
    """
    queries = [q for q in (issuer, cusip) if q]
    for query in queries:
        try:
            data = get_json(f"{THIRTEENF_BASE}/data/autocomplete?q={query}", no_cache=no_cache)
        except FetchError:
            continue
        for c in data.get("cusips", []):
            hit = (c.get("url") or "").rsplit("/", 1)[-1]
            if hit != cusip and hit.lstrip("0") != cusip.lstrip("0"):
                continue
            symbol, sep, _ = (c.get("name") or "").partition(" - ")
            symbol = symbol.strip()
            if sep and symbol and " " not in symbol:
                return symbol
    return None


@app.command
def institutions(json: JsonFlag = False) -> None:
    """Print the built-in institution watchlist (no network)."""
    if json:
        print_json(WATCHLIST)
        return
    render_table(
        "Watchlist",
        ["Name", "CIK", "Category"],
        ([i["name"], i["cik"], i["category"]] for i in WATCHLIST),
    )


@app.command
def search(query: str, json: JsonFlag = False, no_cache: NoCacheFlag = False) -> None:
    """Search 13f.info for managers and companies/CUSIPs."""

    def _go() -> None:
        data = get_json(f"{THIRTEENF_BASE}/data/autocomplete?q={query}", no_cache=no_cache)
        if json:
            print_json(data)
            return
        managers = [
            [m.get("name", ""), m.get("extra", ""), _manager_cik(m.get("url", ""))]
            for m in data.get("managers", [])
        ]
        render_table(f"Managers matching '{query}'", ["Name", "Location", "CIK"], managers)
        cusips = []
        for c in data.get("cusips", []):
            symbol, _, issuer = (c.get("name") or "").partition(" - ")
            cusip = (c.get("url") or "").rsplit("/", 1)[-1]
            cusips.append([issuer.strip() or symbol.strip(), symbol.strip() if issuer else "", cusip])
        render_table(f"CUSIPs matching '{query}'", ["Issuer", "Symbol", "CUSIP"], cusips)

    _run(_go)


@app.command
def holdings(
    external_id: str,
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Aggregated holdings for a 13F filing (external_id = accession number, dashes optional)."""

    def _go() -> None:
        eid = _external_id(external_id)
        data = get_json(f"{THIRTEENF_BASE}/data/13f/{eid}", no_cache=no_cache)
        if json:
            print_json(data)
            return
        # rows: [symbol, issuer_name, class_title, cusip, value_thousands, pct, shares, ...]
        rows = sorted(data.get("data", []), key=lambda r: (r[4] is None, -(r[4] or 0)))
        if limit:
            rows = rows[:limit]
        render_table(
            f"Holdings — {eid}",
            ["Symbol", "Issuer", "Class", "CUSIP", "Value ($000)", "% Port", "Shares"],
            (
                [r[0] or "-", trunc(r[1], 24), trunc(r[2], 14), r[3], fmt_usd_thousands(r[4]), fmt_pct(r[5]), fmt_int(r[6])]
                for r in rows
            ),
        )

    _run(_go)


# --- compare -------------------------------------------------------------

# compare rows (13 fields):
# [symbol, issuer, class_title, cusip, put_call, shares_before, shares_after,
#  shares_delta, shares_delta_pct, value_before, value_after, value_delta,
#  value_delta_pct]   (values in $thousands)


def _compare_rows(eid: str, other: str, no_cache: bool = False) -> list[list]:
    data = get_json(f"{THIRTEENF_BASE}/data/13f/{eid}/compare/{other}", no_cache=no_cache)
    return data.get("data", [])


def _classify(r: list) -> str:
    """Classify a compare row by its value before/after/delta."""
    before, after, delta = r[9] or 0, r[10] or 0, r[11] or 0
    if before == 0 and after > 0:
        return "new"
    if after == 0 and before > 0:
        return "closed"
    if delta > 0:
        return "increased"
    if delta < 0:
        return "reduced"
    return "unchanged"


def _pct_desc(r: list) -> tuple:
    """Sort by value delta % desc, None last."""
    return (r[12] is None, -(r[12] or 0))


ONLY_KINDS = ("new", "increased", "reduced", "closed")
ONLY_TITLES = {
    "new": "NEW POSITIONS",
    "increased": "INCREASED POSITIONS",
    "reduced": "REDUCED POSITIONS",
    "closed": "CLOSED POSITIONS",
}


def _validate_only(only: Optional[list[str]]) -> list[str]:
    """Validate --only choices; exit 2 with a clean message on bad values."""
    bad = [o for o in only if o not in ONLY_KINDS]
    if bad:
        err_console.print(
            f"[red]Error:[/red] invalid --only value(s): {', '.join(bad)} "
            f"(choose from: {', '.join(ONLY_KINDS)})"
        )
        raise SystemExit(2)
    # canonical order, de-duplicated
    return [k for k in ONLY_KINDS if k in set(only)]


def _only_row(r: list, total_after: int) -> list[str]:
    """Full row for a --only table: Symbol, Issuer, CUSIP, before/after, % port."""
    after = r[10] or 0
    pct = (after / total_after * 100) if total_after and after else None
    return [
        trunc(r[0], 6) if r[0] else "-",
        trunc(r[1], 24),
        r[3],
        fmt_usd_thousands(r[9]),
        fmt_usd_thousands(r[10]),
        fmt_int(r[5]),
        fmt_int(r[6]),
        f"{pct:.2f}%" if pct is not None else "-",
    ]


def _compare_row(r: list, detailed: bool) -> list[str]:
    kind = _classify(r)
    marker = {"new": "[bold green]NEW[/bold green]", "closed": "[bold red]CLOSED[/bold red]"}.get(kind, "")
    color = "green" if (r[11] or 0) > 0 else "red"
    cells = [marker, trunc(r[0], 6) if r[0] else "-", trunc(r[1], 24)]
    if detailed:
        cells.append(trunc(r[2], 12))
    cells.append(r[3])
    if detailed:
        cells.append(r[4] or "-")
    cells += [
        fmt_usd_thousands(r[9]),
        fmt_usd_thousands(r[10]),
        f"[{color}]{fmt_usd_thousands(r[11])}[/{color}]",
        f"[{color}]{fmt_pct(r[12])}[/{color}]",
        f"[{color}]{fmt_pct(r[8])}[/{color}]",
    ]
    return cells


@app.command
def compare(
    external_id: str,
    other_external_id: str,
    only: OnlyOpt = None,
    limit: LimitOpt = None,
    all: Annotated[bool, Parameter(name="--all", help="Include unchanged positions.")] = False,
    detailed: Annotated[bool, Parameter(name="--detailed", help="Add Class and Put/Call columns.")] = False,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Compare two 13F filings: summary panel + split increased/decreased tables."""

    kinds = _validate_only(only) if only else None

    def _go() -> None:
        eid, other = _external_id(external_id), _external_id(other_external_id)
        rows = _compare_rows(eid, other, no_cache=no_cache)
        if json:
            if kinds:
                rows = [r for r in rows if _classify(r) in kinds]
            print_json({"data": rows})
            return

        counts = Counter(_classify(r) for r in rows)
        total_before = sum(r[9] or 0 for r in rows)
        total_after = sum(r[10] or 0 for r in rows)
        total_delta = total_after - total_before
        delta_pct = (total_delta / total_before * 100) if total_before else None
        top_adds = sorted(
            (r for r in rows if (r[11] or 0) > 0), key=lambda r: -(r[11] or 0)
        )[:3]
        adds_text = (
            " · ".join(
                f"{r[0] or trunc(r[1], 14)} +{fmt_usd_thousands(r[11])}" for r in top_adds
            )
            or "-"
        )
        delta_color = "green" if total_delta >= 0 else "red"
        console.print(
            Panel(
                f"[bold]{eid}[/bold]  (new)  vs  [bold]{other}[/bold]  (old)\n"
                f"Portfolio value: {fmt_usd_thousands(total_before)} → "
                f"{fmt_usd_thousands(total_after)} "
                f"([{delta_color}]${total_delta:+,} "
                f"{fmt_pct(delta_pct)}[/{delta_color}]) ($000)\n"
                f"[green]new {counts['new']}[/green] · "
                f"[green]increased {counts['increased']}[/green] · "
                f"[red]reduced {counts['reduced']}[/red] · "
                f"[red]closed {counts['closed']}[/red] · "
                f"unchanged {counts['unchanged']}\n"
                f"Top adds: {adds_text}",
                title="Compare summary",
                title_align="left",
            )
        )

        if kinds is not None:
            # --only: one clearly-labeled table per requested group, full rows.
            only_columns = [
                "Symbol", "Issuer", "CUSIP", "Val Before", "Val After",
                "Shrs Before", "Shrs After", "% Port",
            ]
            for kind in kinds:
                subset = [r for r in rows if _classify(r) == kind]
                if kind in ("new", "increased"):
                    subset.sort(key=lambda r: (r[10] is None, -(r[10] or 0)))
                else:
                    subset.sort(key=lambda r: (r[9] is None, -(r[9] or 0)))
                total = len(subset)
                if limit:
                    subset = subset[:limit]
                render_table(
                    f"{ONLY_TITLES[kind]} ({len(subset)} of {total})",
                    only_columns,
                    (_only_row(r, total_after) for r in subset),
                )
            return

        columns = ["", "Symbol", "Issuer"]
        if detailed:
            columns.append("Class")
        columns.append("CUSIP")
        if detailed:
            columns.append("P/C")
        columns += ["Val Before", "Val After", "Val Δ", "Val Δ%", "Shrs Δ%"]

        groups = [
            ("INCREASED / NEW", lambda k: k in ("new", "increased")),
            ("DECREASED / CLOSED", lambda k: k in ("reduced", "closed")),
        ]
        if all:
            groups.append(("UNCHANGED", lambda k: k == "unchanged"))
        for title, pred in groups:
            subset = sorted((r for r in rows if pred(_classify(r))), key=_pct_desc)
            if limit:
                subset = subset[:limit]
            render_table(
                f"{title} ({len(subset)}{' shown' if limit else ''})",
                columns,
                (_compare_row(r, detailed) for r in subset),
            )

    _run(_go)


# --- holders -------------------------------------------------------------


@app.command
def holders(
    cusip: Annotated[str, Parameter(help="9-char CUSIP, e.g. 172573107 for CRCL.")],
    year: Annotated[int, Parameter(help="Report year, e.g. 2026.")],
    quarter: Annotated[int, Parameter(help="Report quarter, 1-4.")],
    limit: Annotated[int, Parameter(help="Max managers to list.")] = 25,
    symbol: Annotated[
        Optional[str],
        Parameter(name="--symbol", help="Ticker for % of shares outstanding (auto-resolved when omitted)."),
    ] = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """All managers holding a CUSIP in a given quarter (sorted by value desc)."""

    def _go() -> None:
        data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{year}/{quarter}", no_cache=no_cache)
        if json:
            print_json(data)
            return
        # rows: [[manager_name, cik, cusip], [period_end, filing_slug], value_thousands, shares, ...]
        rows = sorted(data.get("data", []), key=lambda r: (r[2] is None, -(r[2] or 0)))
        if limit:
            rows = rows[:limit]
        render_table(
            f"Holders of {cusip} — {year} Q{quarter}",
            ["Manager", "CIK", "Period End", "Value ($000)", "Shares", "Filing"],
            (
                [trunc(r[0][0], 28), r[0][1], r[1][0], fmt_usd_thousands(r[2]), fmt_int(r[3]), trunc(r[1][1], 22)]
                for r in rows
            ),
        )
        # summary footer
        total_value = sum(r[2] or 0 for r in rows)
        total_shares = sum(r[3] or 0 for r in rows)
        console.print(
            f"[bold]Totals across {len(rows)} listed managers:[/bold] "
            f"{fmt_int(total_shares)} shares · {fmt_usd_thousands(total_value)} ($000)"
        )
        sym = symbol or _resolve_symbol(cusip, no_cache=no_cache)
        if not sym:
            err_console.print("[dim]no ticker resolvable for this CUSIP; pass --symbol for % of shares outstanding[/dim]")
            return
        quote = get_quote(sym, no_cache=no_cache)
        shares_out = quote.get("shares_outstanding")
        if shares_out:
            console.print(
                f"[bold]{sym}[/bold] shares outstanding: {fmt_int(shares_out)} → "
                f"listed managers hold [bold]{total_shares / shares_out * 100:.2f}%[/bold]"
            )
        else:
            err_console.print(
                f"[dim]resolved {sym}, but no shares-outstanding data (yfinance unavailable or rate-limited)[/dim]"
            )

    _run(_go)


# --- position (per-ticker consensus) -------------------------------------

_WATCHLIST_BY_CIK = {i["cik"].zfill(10): i for i in WATCHLIST}
_WL_BADGE = {"biotech": "BIO", "megafund": "MEGA"}


def _prev_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def _resolve_cusip_info(cusip: str, *, no_cache: bool = False) -> tuple[Optional[str], Optional[str]]:
    """(symbol, issuer) for a CUSIP via 13f.info autocomplete (queried by CUSIP)."""
    try:
        data = get_json(f"{THIRTEENF_BASE}/data/autocomplete?q={cusip}", no_cache=no_cache)
    except FetchError:
        return None, None
    for c in data.get("cusips", []):
        hit = (c.get("url") or "").rsplit("/", 1)[-1]
        if hit != cusip and hit.lstrip("0") != cusip.lstrip("0"):
            continue
        symbol, sep, issuer = (c.get("name") or "").partition(" - ")
        symbol = symbol.strip()
        symbol = symbol if (sep and symbol and " " not in symbol) else None
        return symbol, (issuer.strip() or None)
    return None, None


def _holders_by_cik(rows: list[list]) -> dict[str, dict[str, Any]]:
    """Aggregate holders-endpoint rows by manager CIK (sums put/call rows).

    Row shape: [[manager_name, cik, cusip], [period_end, slug], value, shares, ...]
    """
    by_cik: dict[str, dict[str, Any]] = {}
    for r in rows:
        cik = str(r[0][1]).strip().zfill(10)
        e = by_cik.setdefault(
            cik, {"name": r[0][0], "cik": cik, "value": 0, "shares": 0}
        )
        e["value"] += r[2] or 0
        e["shares"] += r[3] or 0
    return by_cik


@app.command
def position(
    cusip: Annotated[str, Parameter(help="9-char CUSIP, e.g. 172573107 for CRCL.")],
    year: Annotated[int, Parameter(help="Report year, e.g. 2026.")],
    quarter: Annotated[int, Parameter(help="Report quarter, 1-4.")],
    symbol: Annotated[
        Optional[str],
        Parameter(name="--symbol", help="Ticker symbol (auto-resolved via 13f.info autocomplete when omitted)."),
    ] = None,
    limit: Annotated[int, Parameter(name="--limit", help="Max managers to list.")] = 25,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Quarter-over-quarter holder consensus for ONE ticker (CUSIP).

    Renders holders regrouped into INCREASED/NEW, REDUCED/CLOSED and UNCHANGED
    tables (--limit applies per group) and totals shares / % of outstanding
    across ALL listed managers, not just the watchlist.
    """

    def _go() -> None:
        cur_data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{year}/{quarter}", no_cache=no_cache)
        cur_rows = cur_data.get("data", []) or []
        py, pq = _prev_quarter(year, quarter)
        prev_rows: list[list] = []
        prev_available = True
        try:
            prev_data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{py}/{pq}", no_cache=no_cache)
            prev_rows = prev_data.get("data", []) or []
        except FetchError:
            prev_available = False
        if not prev_rows:
            prev_available = False

        cur = _holders_by_cik(cur_rows)
        prev = _holders_by_cik(prev_rows)

        # classify every manager seen in either quarter
        records: list[dict[str, Any]] = []
        for cik in sorted(set(cur) | set(prev)):
            now, before = cur.get(cik), prev.get(cik)
            name = (now or before)["name"]
            if not prev_available:
                status = "NEW"
            elif now and not before:
                status = "NEW"
            elif before and not now:
                status = "CLOSED"
            elif now["shares"] > before["shares"]:
                status = "INCREASED"
            elif now["shares"] < before["shares"]:
                status = "REDUCED"
            else:
                status = "UNCHANGED"
            value_now = now["value"] if now else 0
            value_prev = before["value"] if before else 0
            shares_now = now["shares"] if now else 0
            shares_prev = before["shares"] if before else 0
            inst = _WATCHLIST_BY_CIK.get(cik)
            records.append(
                {
                    "manager": name,
                    "cik": cik,
                    "watchlist": _WL_BADGE.get(inst["category"], "") if inst else "",
                    "status": status,
                    "shares_now": shares_now,
                    "shares_prev": shares_prev,
                    "shares_delta": shares_now - shares_prev,
                    "value_now": value_now,
                    "value_prev": value_prev,
                    "value_delta": value_now - value_prev,
                }
            )
        records.sort(key=lambda d: -max(d["value_now"], d["value_prev"]))

        counts = Counter(d["status"] for d in records)
        wl = [d for d in records if d["watchlist"]]
        wl_now = [d for d in wl if d["value_now"] > 0]
        wl_prev = [d for d in wl if d["value_prev"] > 0]
        wl_shares_delta = sum(d["shares_delta"] for d in wl)
        wl_value_delta = sum(d["value_delta"] for d in wl)
        wl_shares_now = sum(d["shares_now"] for d in wl)
        wl_shares_prev = sum(d["shares_prev"] for d in wl)
        # totals across ALL listed managers (not just the watchlist)
        all_shares_now = sum(d["shares_now"] for d in records)
        all_shares_prev = sum(d["shares_prev"] for d in records)
        all_shares_delta = sum(d["shares_delta"] for d in records)
        all_value_now = sum(d["value_now"] for d in records)
        all_value_delta = sum(d["value_delta"] for d in records)

        # symbol / issuer resolution + yfinance enrichment (best-effort)
        sym = symbol.strip().upper() if symbol else None
        issuer = None
        if not sym:
            sym, issuer = _resolve_cusip_info(cusip, no_cache=no_cache)
        else:
            _, issuer = _resolve_cusip_info(cusip, no_cache=no_cache)
        quote: dict[str, Any] = get_quote(sym, no_cache=no_cache) if sym else {}
        shares_out = quote.get("shares_outstanding")
        wl_pct_now = (wl_shares_now / shares_out * 100) if shares_out else None
        wl_pct_prev = (wl_shares_prev / shares_out * 100) if shares_out else None
        all_pct_now = (all_shares_now / shares_out * 100) if shares_out else None
        all_pct_prev = (all_shares_prev / shares_out * 100) if shares_out else None
        for d in records:
            d["pct_out"] = (d["shares_now"] / shares_out * 100) if shares_out else None

        if json:
            print_json(
                {
                    "cusip": cusip,
                    "year": year,
                    "quarter": quarter,
                    "prev_year": py,
                    "prev_quarter": pq,
                    "prev_data": prev_available,
                    "issuer": issuer,
                    "symbol": sym,
                    "holders_now": len(cur),
                    "holders_prev": len(prev),
                    "counts": {k: counts.get(k, 0) for k in ("NEW", "INCREASED", "REDUCED", "CLOSED", "UNCHANGED")},
                    "watchlist": {
                        "holders_now": len(wl_now),
                        "holders_prev": len(wl_prev),
                        "net_shares_delta": wl_shares_delta,
                        "net_value_delta": wl_value_delta,
                        "pct_out_now": wl_pct_now,
                        "pct_out_prev": wl_pct_prev,
                    },
                    "all": {
                        "holders_now": len(cur),
                        "holders_prev": len(prev),
                        "shares_now": all_shares_now,
                        "shares_prev": all_shares_prev,
                        "net_shares_delta": all_shares_delta,
                        "net_value_delta": all_value_delta,
                        "pct_out_now": all_pct_now,
                        "pct_out_prev": all_pct_prev,
                    },
                    "quote": quote,
                    "rows": records,
                }
            )
            return

        if not prev_available:
            err_console.print(
                f"[yellow]note: no previous-quarter data ({py} Q{pq}) on 13f.info — "
                "all current holders shown as NEW[/yellow]"
            )

        lines = [
            f"[bold]{issuer or '-'}[/bold] ({sym or '-'}) — {cusip} — {year} Q{quarter} vs {py} Q{pq}",
            f"Holders: {len(cur)} now (prev {len(prev) if prev_available else 'n/a'})",
            f"[green]NEW {counts.get('NEW', 0)}[/green] · "
            f"[green]INCREASED {counts.get('INCREASED', 0)}[/green] · "
            f"[red]REDUCED {counts.get('REDUCED', 0)}[/red] · "
            f"[red]CLOSED {counts.get('CLOSED', 0)}[/red] · "
            f"UNCHANGED {counts.get('UNCHANGED', 0)}",
            f"Watchlist: {len(wl_now)} holders now (prev {len(wl_prev)}) · "
            f"net shares Δ [{'green' if wl_shares_delta >= 0 else 'red'}]{wl_shares_delta:+,}[/] · "
            f"net value Δ [{'green' if wl_value_delta >= 0 else 'red'}]${wl_value_delta:+,}[/] ($000)",
            f"All listed: {len(records)} managers · "
            f"net shares Δ [{'green' if all_shares_delta >= 0 else 'red'}]{all_shares_delta:+,}[/] · "
            f"net value Δ [{'green' if all_value_delta >= 0 else 'red'}]${all_value_delta:+,}[/] ($000)",
        ]
        if sym and quote:
            price = quote.get("last_price")
            lines.append(
                f"[bold]{sym}[/bold] "
                f"price {f'${price:,.2f}' if isinstance(price, (int, float)) else '-'} · "
                f"mkt cap {fmt_usd(quote.get('market_cap'))} · "
                f"shares out {fmt_int(shares_out)}"
            )
        if wl_pct_now is not None and wl_pct_prev is not None:
            delta_pp = wl_pct_now - wl_pct_prev
            lines.append(
                f"Watchlist % Out: {wl_pct_now:.2f}% now vs {wl_pct_prev:.2f}% prev "
                f"([{'green' if delta_pp >= 0 else 'red'}]{delta_pp:+.2f}pp[/])"
            )
        if all_pct_now is not None and all_pct_prev is not None:
            delta_pp = all_pct_now - all_pct_prev
            lines.append(
                f"All listed % Out: {all_pct_now:.2f}% now vs {all_pct_prev:.2f}% prev "
                f"([{'green' if delta_pp >= 0 else 'red'}]{delta_pp:+.2f}pp[/])"
            )
        console.print(Panel("\n".join(lines), title="Position consensus", title_align="left"))

        _STATUS_MARKUP = {
            "NEW": "[bold green]NEW[/bold green]",
            "INCREASED": "[green]INCREASED[/green]",
            "REDUCED": "[red]REDUCED[/red]",
            "CLOSED": "[bold red]CLOSED[/bold red]",
            "UNCHANGED": "[dim]UNCHANGED[/dim]",
        }
        columns = ["Manager", "CIK", "Watchlist", "Status", "Shares", "Shares Δ", "Value ($000)", "Value Δ ($000)", "% Out"]

        def _row(d: dict[str, Any]) -> list[str]:
            return [
                trunc(d["manager"], 28),
                d["cik"],
                d["watchlist"],
                _STATUS_MARKUP[d["status"]],
                fmt_int(d["shares_now"]) if d["status"] != "CLOSED" else "0",
                f"[{'green' if d['shares_delta'] >= 0 else 'red'}]{d['shares_delta']:+,}[/]",
                fmt_usd_thousands(d["value_now"]) if d["status"] != "CLOSED" else "$0",
                f"[{'green' if d['value_delta'] >= 0 else 'red'}]${d['value_delta']:+,}[/]",
                f"{d['pct_out']:.2f}%" if d["pct_out"] is not None else "-",
            ]

        # regroup by status: buyers together, sellers together, unchanged last
        groups = [
            ("INCREASED / NEW", ("NEW", "INCREASED")),
            ("REDUCED / CLOSED", ("REDUCED", "CLOSED")),
            ("UNCHANGED", ("UNCHANGED",)),
        ]
        for title, statuses in groups:
            subset = [d for d in records if d["status"] in statuses]
            if not subset:
                continue
            shown = subset[:limit] if limit else subset
            render_table(
                f"{title} — {cusip} {year} Q{quarter} vs {py} Q{pq} ({len(shown)} of {len(subset)})",
                columns,
                (_row(d) for d in shown),
            )
        footer = (
            f"[bold]Totals across all {len(records)} listed managers:[/bold] "
            f"{fmt_int(all_shares_now)} shares now (prev {fmt_int(all_shares_prev)}) · "
            f"{fmt_usd_thousands(all_value_now)} ($000)"
        )
        if all_pct_now is not None:
            footer += f" → [bold]{all_pct_now:.2f}%[/bold] of shares outstanding"
        console.print(footer)

    _run(_go)


@app.command
def history(
    cik: str,
    cusip: str,
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """One manager's position history in one stock."""

    def _go() -> None:
        data = get_json(f"{THIRTEENF_BASE}/data/manager/{cik}/cusip/{cusip}", no_cache=no_cache)
        if json:
            print_json(data)
            return
        # rows: [[period_end, filing_slug], value_thousands, pct, shares, put_call,
        #        filing_date, [year, quarter]]
        rows = data.get("data", [])
        if limit:
            rows = rows[:limit]
        render_table(
            f"History — manager {cik} / {cusip}",
            ["Period End", "Value ($000)", "% Port", "Shares", "Filed", "Filing"],
            (
                [r[0][0], fmt_usd_thousands(r[1]), fmt_pct(r[2]), fmt_int(r[3]), r[5], trunc(r[0][1], 24)]
                for r in rows
            ),
        )

    _run(_go)


@app.command
def filings(
    cik: str,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Recent 13F filings for a CIK from SEC EDGAR (external_id pipes into holdings/compare)."""

    def _go() -> None:
        records = _edgar_13f_filings(cik, no_cache=no_cache)
        padded = cik.strip().zfill(10)
        if json:
            print_json(records)
            return
        render_table(
            f"13F filings — CIK {padded}",
            ["Form", "Filed", "Period", "Accession Number", "external_id", "Note"],
            (
                [
                    r["form"], r["filing_date"], r["report_date"] or "-",
                    r["accession_number"], r["external_id"],
                    "AMENDMENT" if r["amendment"] else "",
                ]
                for r in records
            ),
        )

    _run(_go)


def _edgar_13f_filings(cik: str, *, no_cache: bool = False) -> list[dict[str, Any]]:
    """All 13F* filings from EDGAR submissions for a CIK (newest first)."""
    padded = cik.strip().zfill(10)
    data = get_json(f"{EDGAR_BASE}/submissions/CIK{padded}.json", no_cache=no_cache)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    records: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        if not form or not form.startswith("13F"):
            continue
        accession = recent["accessionNumber"][i]
        records.append(
            {
                "form": form,
                "filing_date": recent["filingDate"][i],
                "report_date": recent.get("reportDate", [None] * len(forms))[i],
                "accession_number": accession,
                "external_id": accession.replace("-", ""),
                "amendment": form.endswith("/A"),
            }
        )
    return records


# --- ticker (yfinance) ---------------------------------------------------


@app.command
def ticker(symbol: str, json: JsonFlag = False, no_cache: NoCacheFlag = False) -> None:
    """Quote & profile for a ticker symbol via yfinance (best-effort)."""
    quote = get_quote(symbol, no_cache=no_cache)
    if not quote:
        err_console.print(
            f"[red]Error:[/red] no data for '{symbol.upper()}' — symbol not found, "
            "or yfinance unavailable/rate-limited."
        )
        raise SystemExit(1)
    if json:
        print_json(quote)
        return
    year_range = "-"
    if quote.get("year_low") is not None and quote.get("year_high") is not None:
        year_range = f"{quote['year_low']:,.2f} – {quote['year_high']:,.2f}"
    last_price = quote.get("last_price")
    render_table(
        f"Ticker — {symbol.upper()}",
        ["Field", "Value"],
        [
            ["Name", quote.get("name") or "-"],
            ["Symbol", symbol.upper()],
            ["Sector", quote.get("sector") or "-"],
            ["Industry", quote.get("industry") or "-"],
            ["Market Cap", fmt_usd(quote.get("market_cap"))],
            ["Shares Outstanding", fmt_int(quote.get("shares_outstanding"))],
            ["Float Shares", fmt_int(quote.get("float_shares"))],
            ["Last Price", f"${last_price:,.2f}" if isinstance(last_price, (int, float)) else "-"],
            ["52w Range", year_range],
            ["Avg Volume (3m)", fmt_int(quote.get("avg_volume"))],
        ],
    )


# --- consensus -----------------------------------------------------------


def _latest_two_periods(cik: str, *, no_cache: bool = False) -> Optional[tuple[str, str]]:
    """(new_eid, old_eid) for the 2 most recent report periods of a CIK.

    Filings are grouped by report period; the latest filing per period wins
    (13F-HR/A amendments supersede the original 13F-HR). Returns None when the
    CIK has fewer than 2 report periods.
    """
    best: dict[str, tuple[str, str]] = {}  # report period -> (filing_date, accession)
    for rec in _edgar_13f_filings(cik, no_cache=no_cache):
        period = rec["report_date"] or rec["filing_date"]
        if not period:
            continue
        cur = best.get(period)
        if cur is None or (rec["filing_date"] or "") > cur[0]:
            best[period] = (rec["filing_date"] or "", rec["accession_number"])
    if len(best) < 2:
        return None
    periods = sorted(best, reverse=True)[:2]
    return best[periods[0]][1].replace("-", ""), best[periods[1]][1].replace("-", "")


@app.command
def consensus(
    category: Annotated[str, Parameter(name="--category", help="Watchlist category: biotech | megafund | all.")] = "all",
    ciks: Annotated[Optional[str], Parameter(name="--ciks", help='Comma-separated CIKs, e.g. "0001,0002" (overrides watchlist).')] = None,
    min_funds: Annotated[int, Parameter(name="--min-funds", help="Min distinct funds reporting a CUSIP.")] = 2,
    enrich: Annotated[int, Parameter(name="--enrich", help="Enrich top N rows (symbol + yfinance %% outstanding). 0 disables.")] = 15,
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Aggregate quarter-over-quarter 13F moves across the watchlist by CUSIP."""

    def _go() -> None:
        cat = category.lower()
        if cat not in ("biotech", "megafund", "all"):
            err_console.print(f"[red]Error:[/red] --category must be biotech|megafund|all, got '{category}'")
            raise SystemExit(2)
        label = cat
        if ciks:
            institutions = [
                {"name": c.strip(), "cik": c.strip().zfill(10), "category": "custom"}
                for c in ciks.split(",")
                if c.strip()
            ]
            label = "custom CIKs"
        else:
            institutions = [i for i in WATCHLIST if cat == "all" or i["category"] == cat]
        if not institutions:
            err_console.print("[red]Error:[/red] empty CIK set")
            raise SystemExit(2)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=err_console,
        ) as progress:
            # b+c: per CIK, latest 2 periods -> compare rows
            per_fund: dict[str, list[list]] = {}
            task = progress.add_task("fetching filings", total=len(institutions))
            for inst in institutions:
                cik = inst["cik"]
                progress.update(task, description=f"{trunc(inst['name'], 28)} ({cik})")
                try:
                    pair = _latest_two_periods(cik, no_cache=no_cache)
                except FetchError as exc:
                    err_console.print(f"[yellow]skip {cik} ({inst['name']}): {exc}[/yellow]")
                    progress.advance(task)
                    continue
                if pair is None:
                    err_console.print(
                        f"[dim]skip {cik} ({inst['name']}): fewer than 2 13F report periods[/dim]"
                    )
                    progress.advance(task)
                    continue
                try:
                    rows = _compare_rows(pair[0], pair[1], no_cache=no_cache)
                except FetchError as exc:
                    err_console.print(f"[yellow]skip {cik} ({inst['name']}): {exc}[/yellow]")
                    progress.advance(task)
                    continue
                per_fund[cik] = rows
                progress.advance(task)

        if not per_fund:
            err_console.print("[red]Error:[/red] no compare data for any CIK in the set")
            raise SystemExit(1)

        # d: aggregate by CUSIP across funds
        agg: dict[str, dict[str, Any]] = {}
        for cik, rows in per_fund.items():
            for r in rows:
                cusip = r[3]
                if not cusip:
                    continue
                e = agg.setdefault(
                    cusip,
                    {
                        "issuers": Counter(),
                        "symbol": None,
                        "funds": set(),
                        "new": set(),
                        "inc": set(),
                        "red": set(),
                        "closed": set(),
                        "holding_now": set(),
                        "value_now": 0,
                        "value_delta": 0,
                        "shares_now": 0,
                    },
                )
                if r[1]:
                    e["issuers"][r[1]] += 1
                if e["symbol"] is None and r[0]:
                    e["symbol"] = r[0]
                e["funds"].add(cik)
                kind = _classify(r)
                if kind == "new":
                    e["new"].add(cik)
                elif kind == "increased":
                    e["inc"].add(cik)
                elif kind == "reduced":
                    e["red"].add(cik)
                elif kind == "closed":
                    e["closed"].add(cik)
                if (r[10] or 0) > 0:
                    e["holding_now"].add(cik)
                    e["value_now"] += r[10] or 0
                    e["shares_now"] += r[6] or 0
                e["value_delta"] += r[11] or 0

        # e: filter + sort
        results: list[dict[str, Any]] = []
        for cusip, e in agg.items():
            if len(e["funds"]) < min_funds:
                continue
            results.append(
                {
                    "cusip": cusip,
                    "symbol": e["symbol"],
                    "issuer": e["issuers"].most_common(1)[0][0] if e["issuers"] else "",
                    "funds_reporting": len(e["funds"]),
                    "funds_new": len(e["new"]),
                    "funds_increased": len(e["inc"]),
                    "funds_reduced": len(e["red"]),
                    "funds_closed": len(e["closed"]),
                    "n_funds_holding_now": len(e["holding_now"]),
                    "sum_value_now": e["value_now"],
                    "sum_value_delta": e["value_delta"],
                    "sum_shares_now": e["shares_now"],
                    "net_funds": len(e["new"]) + len(e["inc"]) - len(e["red"]) - len(e["closed"]),
                    "sector": None,
                    "market_cap": None,
                    "watchlist_pct_outstanding": None,
                }
            )
        results.sort(key=lambda d: (-d["net_funds"], -d["sum_value_delta"]))

        # f: enrichment (autocomplete symbol recovery + yfinance)
        if enrich:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=err_console,
            ) as progress:
                top = results[:enrich]
                task = progress.add_task("enriching", total=len(top))
                for d in top:
                    progress.update(task, description=f"enrich {d['cusip']}")
                    if not d["symbol"]:
                        d["symbol"] = _resolve_symbol(d["cusip"], d["issuer"], no_cache=no_cache)
                    if d["symbol"]:
                        quote = get_quote(d["symbol"], no_cache=no_cache)
                        d["sector"] = quote.get("sector")
                        d["market_cap"] = quote.get("market_cap")
                        shares_out = quote.get("shares_outstanding")
                        if shares_out:
                            d["watchlist_pct_outstanding"] = d["sum_shares_now"] / shares_out * 100
                    progress.advance(task)

        if json:
            print_json(results)
            return

        shown = results[:limit] if limit else results
        err_console.print(
            f"[dim]{len(per_fund)}/{len(institutions)} funds · {len(agg)} CUSIPs · "
            f"{len(results)} pass --min-funds {min_funds}[/dim]"
        )
        render_table(
            f"Consensus — {label} ({len(shown)} of {len(results)} rows)",
            ["Symbol", "Issuer", "CUSIP", "Funds", "NEW", "INC", "RED", "CLS", "Net", "Hold", "Val Now ($000)", "Val Δ ($000)", "% Out"],
            (
                [
                    (d["symbol"] or "-"),
                    trunc(d["issuer"], 24),
                    d["cusip"],
                    str(d["funds_reporting"]),
                    f"[green]{d['funds_new']}[/green]" if d["funds_new"] else "0",
                    f"[green]{d['funds_increased']}[/green]" if d["funds_increased"] else "0",
                    f"[red]{d['funds_reduced']}[/red]" if d["funds_reduced"] else "0",
                    f"[red]{d['funds_closed']}[/red]" if d["funds_closed"] else "0",
                    f"[{'green' if d['net_funds'] >= 0 else 'red'}]{d['net_funds']:+d}[/]",
                    str(d["n_funds_holding_now"]),
                    fmt_usd_thousands(d["sum_value_now"]),
                    f"[{'green' if d['sum_value_delta'] >= 0 else 'red'}]{fmt_usd_thousands(d['sum_value_delta'])}[/]",
                    f"{d['watchlist_pct_outstanding']:.2f}%" if d["watchlist_pct_outstanding"] is not None else "-",
                ]
                for d in shown
            ),
        )

    _run(_go)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
