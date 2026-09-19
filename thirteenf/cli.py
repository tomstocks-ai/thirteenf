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

from thirteenf.changes import Change
from thirteenf.client import EDGAR_BASE, THIRTEENF_BASE, FetchError, get_json
from thirteenf.hub import hub_cusips
from thirteenf.quotes import (
    get_institutional_breakdown,
    get_quote,
    get_shares_history,
    shares_asof,
)
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
from thirteenf.watchlist import WATCHLIST, WATCHLIST_ALIASES

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


def categories() -> list[str]:
    """All watchlist categories, sorted."""
    return sorted({i["category"] for i in WATCHLIST})


@app.command
def institutions(
    category: Annotated[
        Optional[str],
        Parameter(name="--category", help="Filter by category (e.g. bank, hedge, biotech); omit for all."),
    ] = None,
    json: JsonFlag = False,
) -> None:
    """Print the built-in institution watchlist, sorted by latest 13F value (no network).

    'Ratings Desk' flags institutions whose affiliates publish sell-side
    analyst ratings — a conflict-of-interest flag when their 13F positions
    move against/around their own published ratings.
    """
    items = list(WATCHLIST)
    if category and category != "all":
        items = [i for i in items if i["category"] == category]
        if not items:
            err_console.print(
                f"[red]Error:[/red] no institutions in category '{category}' "
                f"(choose from: {', '.join(categories())})"
            )
            raise SystemExit(2)
    items.sort(key=lambda i: -(i.get("value_b") or 0))
    if json:
        print_json(items)
        return
    render_table(
        f"Watchlist ({len(items)} institutions, by latest 13F value)",
        ["Name", "CIK", "Category", "13F Value ($B)", "Ratings Desk"],
        (
            [
                i["name"],
                i["cik"],
                i["category"],
                f"{i['value_b']:,.1f}" if i.get("value_b") else "-",
                "[yellow]YES[/yellow]" if i.get("ratings") else "",
            ]
            for i in items
        ),
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


def _filing_row_dict(r: list) -> dict[str, Any]:
    """Named-field dict for a raw 13f.info holdings row (agent-friendly JSON)."""
    return {
        "symbol": r[0],
        "issuer": r[1],
        "class": r[2],
        "cusip": r[3],
        "value_thousands": r[4],
        "pct_portfolio": r[5],
        "shares": r[6],
        "put_call": r[8] if len(r) > 8 else None,
    }


@app.command(name="filing", alias=["holdings"])
def filing(
    external_id: Annotated[
        str,
        Parameter(help="SEC accession number of the filing, dashes optional (find via `13f filings <cik>`)."),
    ],
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Positions reported in ONE 13F filing (alias: holdings).

    --json prints ALL rows with named fields; --limit only affects the table.
    """

    def _go() -> None:
        eid = _external_id(external_id)
        data = get_json(f"{THIRTEENF_BASE}/data/13f/{eid}", no_cache=no_cache)
        # rows: [symbol, issuer_name, class_title, cusip, value_thousands, pct, shares, ?, put_call]
        rows = sorted(data.get("data", []), key=lambda r: (r[4] is None, -(r[4] or 0)))
        if json:
            print_json([_filing_row_dict(r) for r in rows])
            return
        if limit:
            rows = rows[:limit]
        render_table(
            f"Filing {eid} — holdings",
            ["Symbol", "Issuer", "Class", "CUSIP", "Value ($000)", "% Port", "Shares"],
            (
                [r[0] or "-", trunc(r[1], 24), trunc(r[2], 14), r[3], fmt_usd_thousands(r[4]), fmt_pct(r[5]), fmt_int(r[6])]
                for r in rows
            ),
        )

    _run(_go)


# --- compare -------------------------------------------------------------


def _compare_changes(new_id: str, old_id: str, no_cache: bool = False) -> list[Change]:
    """Per-position changes between two filings, as Change objects."""
    data = get_json(f"{THIRTEENF_BASE}/data/13f/{new_id}/compare/{old_id}", no_cache=no_cache)
    return [Change.from_row(r) for r in data.get("data", [])]


def _pct_desc(c: Change) -> tuple:
    """Sort by value delta % desc, None last."""
    return (c.value_delta_pct is None, -(c.value_delta_pct or 0))


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


def _only_row(c: Change, total_after: int) -> list[str]:
    """Full row for a --only table: Symbol, Issuer, CUSIP, before/after, % port."""
    pct = (c.value_after / total_after * 100) if total_after and c.value_after else None
    return [
        trunc(c.symbol, 6) if c.symbol else "-",
        trunc(c.issuer, 24),
        c.cusip,
        fmt_usd_thousands(c.value_before),
        fmt_usd_thousands(c.value_after),
        fmt_int(c.shares_before),
        fmt_int(c.shares_after),
        f"{pct:.2f}%" if pct is not None else "-",
    ]


def _change_row(c: Change, detailed: bool) -> list[str]:
    marker = {"new": "[bold green]NEW[/bold green]", "closed": "[bold red]CLOSED[/bold red]"}.get(c.status, "")
    color = "green" if c.shares_delta > 0 else "red"
    cells = [marker, trunc(c.symbol, 6) if c.symbol else "-", trunc(c.issuer, 24)]
    if detailed:
        cells.append(trunc(c.class_title, 12))
    cells.append(c.cusip)
    if detailed:
        cells.append(c.put_call or "-")
    cells += [
        fmt_usd_thousands(c.value_before),
        fmt_usd_thousands(c.value_after),
        f"[{color}]{fmt_usd_thousands(c.value_delta)}[/{color}]",
        f"[{color}]{fmt_pct(c.value_delta_pct)}[/{color}]",
        f"[{color}]{fmt_pct(c.shares_delta_pct)}[/{color}]",
    ]
    return cells


@app.command
def compare(
    new_id: Annotated[str, Parameter(help="external_id of the NEWER filing (accession number, dashes optional).")],
    old_id: Annotated[str, Parameter(help="external_id of the OLDER filing to compare against.")],
    only: OnlyOpt = None,
    limit: LimitOpt = None,
    all: Annotated[bool, Parameter(name="--all", help="Include unchanged positions.")] = False,
    detailed: Annotated[bool, Parameter(name="--detailed", help="Add Class and Put/Call columns.")] = False,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Compare two 13F filings of one manager: summary panel + split increased/decreased tables.

    Positions are classified by SHARE delta (not value), so price drift is
    never mislabeled as buying/selling — same semantics as `position`.
    """

    kinds = _validate_only(only) if only else None

    def _go() -> None:
        eid, other = _external_id(new_id), _external_id(old_id)
        changes = _compare_changes(eid, other, no_cache=no_cache)
        if json:
            if kinds:
                changes = [c for c in changes if c.status in kinds]
            print_json([c.to_dict() for c in changes])
            return

        counts = Counter(c.status for c in changes)
        total_before = sum(c.value_before for c in changes)
        total_after = sum(c.value_after for c in changes)
        total_delta = total_after - total_before
        delta_pct = (total_delta / total_before * 100) if total_before else None
        top_adds = sorted((c for c in changes if c.value_delta > 0), key=lambda c: -c.value_delta)[:3]
        adds_text = (
            " · ".join(
                f"{c.symbol or trunc(c.issuer, 14)} +{fmt_usd_thousands(c.value_delta)}" for c in top_adds
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
                subset = [c for c in changes if c.status == kind]
                if kind in ("new", "increased"):
                    subset.sort(key=lambda c: -c.value_after)
                else:
                    subset.sort(key=lambda c: -c.value_before)
                total = len(subset)
                if limit:
                    subset = subset[:limit]
                render_table(
                    f"{ONLY_TITLES[kind]} ({len(subset)} of {total})",
                    only_columns,
                    (_only_row(c, total_after) for c in subset),
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
            subset = sorted((c for c in changes if pred(c.status)), key=_pct_desc)
            if limit:
                subset = subset[:limit]
            render_table(
                f"{title} ({len(subset)}{' shown' if limit else ''})",
                columns,
                (_change_row(c, detailed) for c in subset),
            )

    _run(_go)


# --- holders -------------------------------------------------------------


def _holder_row_dict(r: list) -> dict[str, Any]:
    """Named-field dict for a raw 13f.info holders row (agent-friendly JSON)."""
    return {
        "manager": r[0][0],
        "cik": str(r[0][1]).zfill(10),
        "cusip": r[0][2],
        "period_end": r[1][0],
        "filing": r[1][1],
        "value_thousands": r[2],
        "shares": r[3],
        "put_call": r[4] if len(r) > 4 else None,
    }


@app.command
def holders(
    cusip: Annotated[str, Parameter(help="9-char CUSIP, e.g. 172573107 for CRCL.")],
    year: Annotated[int, Parameter(help="Report year, e.g. 2026.")],
    quarter: Annotated[int, Parameter(help="Report quarter, 1-4.")],
    limit: LimitOpt = None,
    symbol: Annotated[
        Optional[str],
        Parameter(name="--symbol", help="Ticker for % of shares outstanding (auto-resolved when omitted)."),
    ] = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """All managers holding a CUSIP in a given quarter (sorted by value desc).

    --json prints ALL rows with named fields; --limit only affects the table.
    """

    def _go() -> None:
        data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{year}/{quarter}", no_cache=no_cache)
        # rows: [[manager_name, cik, cusip], [period_end, filing_slug], value_thousands, shares, put_call]
        rows = sorted(data.get("data", []), key=lambda r: (r[2] is None, -(r[2] or 0)))
        if json:
            print_json([_holder_row_dict(r) for r in rows])
            return
        if limit:
            rows = rows[:limit]
        render_table(
            f"Holders of {cusip} — {year} Q{quarter} ({len(rows)} shown)",
            ["Manager", "CIK", "Period End", "Value ($000)", "Shares", "Filing"],
            (
                [trunc(r[0][0], 28), r[0][1], r[1][0], fmt_usd_thousands(r[2]), fmt_int(r[3]), trunc(r[1][1], 22)]
                for r in rows
            ),
        )
        # summary footer
        total_value = sum(r[2] or 0 for r in rows)
        total_shares = sum(r[3] or 0 for r in rows)
        total_common = sum(r[3] or 0 for r in rows if not (len(r) > 4 and r[4]))
        console.print(
            f"[bold]Totals across {len(rows)} listed managers:[/bold] "
            f"{fmt_int(total_shares)} shares ({fmt_int(total_common)} common) · {fmt_usd_thousands(total_value)} ($000)"
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
                f"listed managers hold [bold]{total_common / shares_out * 100:.2f}%[/bold] (common shs)"
            )
        else:
            err_console.print(
                f"[dim]resolved {sym}, but no shares-outstanding data (yfinance unavailable or rate-limited)[/dim]"
            )

    _run(_go)


# --- position (per-ticker consensus) -------------------------------------

_WATCHLIST_BY_CIK = {i["cik"].zfill(10): i for i in WATCHLIST}
for _alias, _parent in WATCHLIST_ALIASES.items():
    _p = _WATCHLIST_BY_CIK.get(_parent)
    if _p is not None:
        _WATCHLIST_BY_CIK[_alias] = _p  # sub-filer rolls up to parent entry
_RATINGS_BY_CIK = {cik: bool(i.get("ratings")) for cik, i in _WATCHLIST_BY_CIK.items()}


def _badge(inst: dict[str, Any]) -> str:
    """Watchlist badge: short category code, '·R' suffix for sell-side ratings desks."""
    badge = inst["category"].upper()[:6]
    return f"{badge}·R" if inst.get("ratings") else badge


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
    """Aggregate holders-endpoint rows by manager CIK.

    Row shape: [[manager_name, cik, cusip], [period_end, slug], value, shares, put_call]
    `shares` sums all rows (exposure, incl. option legs); `shares_common`
    excludes put/call rows — the right numerator for % of shares outstanding.
    """
    by_cik: dict[str, dict[str, Any]] = {}
    for r in rows:
        cik = str(r[0][1]).strip().zfill(10)
        e = by_cik.setdefault(
            cik, {"name": r[0][0], "cik": cik, "value": 0, "shares": 0, "shares_common": 0}
        )
        e["value"] += r[2] or 0
        e["shares"] += r[3] or 0
        if not (len(r) > 4 and r[4]):  # not a put/call leg
            e["shares_common"] += r[3] or 0
    return by_cik


# --- 13F aggregate cleaning (shared by `position` and `evolution`) ---------

_PRICE_TOLERANCE = 10.0  # implied-price outlier cutoff, as a multiple of the median


def _accession(row: list) -> str:
    """Accession number from a holders-endpoint row's filing slug."""
    return str(row[1][1]).split("-", 1)[0]


def _latest_filing_rows(rows: list[list]) -> list[list]:
    """Keep only each filer's latest accession, preserving all of its line items.

    A manager legitimately reports several rows per CUSIP in ONE filing (share
    classes, option legs, sub-accounts) and those must be summed. But an
    amendment or restatement arrives under a HIGHER accession number and
    supersedes the original — summing both double-counts the position.
    """
    best: dict[str, str] = {}
    for r in rows:
        cik = str(r[0][1]).strip().zfill(10)
        acc = _accession(r)
        if cik not in best or acc > best[cik]:
            best[cik] = acc
    return [r for r in rows if _accession(r) == best[str(r[0][1]).strip().zfill(10)]]


def _implied_price(row: list) -> Optional[float]:
    """Implied per-share price for a row (13F value is in $thousands)."""
    value, shares = row[2], row[3]
    if not value or not shares:
        return None
    return value * 1000.0 / shares


def _drop_price_outliers(rows: list[list]) -> list[list]:
    """Drop rows whose implied price is >_PRICE_TOLERANCE x off the cross-filer median.

    Catches filer unit errors — e.g. CalSTRS reported 6,446,426,607 AAPL shares
    against $22.3B in 2026Q2 (value and shares transposed), an implied $3.46 vs
    a ~$289 median, single-handedly adding 6.4B phantom shares to the total.
    """
    prices = [p for p in (_implied_price(r) for r in rows) if p]
    if len(prices) < 5:  # too few rows to establish a reference price
        return rows
    median = sorted(prices)[len(prices) // 2]
    lo, hi = median / _PRICE_TOLERANCE, median * _PRICE_TOLERANCE
    return [r for r in rows if (p := _implied_price(r)) is None or lo <= p <= hi]


def _clean_rows(rows: list[list]) -> tuple[list[list], int]:
    """(cleaned rows, rows dropped) — supersede amendments, then drop unit errors."""
    if not rows:
        return [], 0
    cleaned = _drop_price_outliers(_latest_filing_rows(rows))
    return cleaned, len(rows) - len(cleaned)


def _aggregate_13f(cusip: str, year: int, quarter: int, *, no_cache: bool = False) -> dict[str, Any]:
    """Cleaned 13F totals for a CUSIP in one quarter. Missing quarter -> zeros."""
    empty = {"filers": 0, "rows_dropped": 0, "common_shares": 0, "value_thousands": 0}
    try:
        data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{year}/{quarter}", no_cache=no_cache)
    except FetchError:
        return empty
    rows = data.get("data", []) or []
    if not rows:
        return empty
    cleaned, dropped = _clean_rows(rows)
    return {
        "filers": len({str(r[0][1]).strip().zfill(10) for r in cleaned}),
        "rows_dropped": dropped,
        "common_shares": sum((r[3] or 0) for r in cleaned if not (len(r) > 4 and r[4])),
        "value_thousands": sum((r[2] or 0) for r in cleaned),
    }


@app.command
def position(
    cusip: Annotated[str, Parameter(help="9-char CUSIP, e.g. 172573107 for CRCL.")],
    year: Annotated[int, Parameter(help="Report year, e.g. 2026.")],
    quarter: Annotated[int, Parameter(help="Report quarter, 1-4.")],
    symbol: Annotated[
        Optional[str],
        Parameter(name="--symbol", help="Ticker symbol (auto-resolved via 13f.info autocomplete when omitted)."),
    ] = None,
    limit: Annotated[int, Parameter(name="--limit", help="Max managers to list per group.")] = 25,
    all: Annotated[bool, Parameter(name="--all", help="Include unchanged holders.")] = False,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Quarter-over-quarter holder consensus for ONE ticker (CUSIP).

    Renders holders regrouped into INCREASED/NEW and REDUCED/CLOSED tables
    (--limit applies per group, --all adds UNCHANGED) and totals shares /
    % of outstanding across ALL listed managers, not just the watchlist.
    """

    def _go() -> None:
        cur_data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{year}/{quarter}", no_cache=no_cache)
        cur_rows, cur_dropped = _clean_rows(cur_data.get("data", []) or [])
        py, pq = _prev_quarter(year, quarter)
        prev_rows: list[list] = []
        prev_dropped = 0
        prev_available = True
        try:
            prev_data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{py}/{pq}", no_cache=no_cache)
            prev_rows, prev_dropped = _clean_rows(prev_data.get("data", []) or [])
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
                    "watchlist": _badge(inst) if inst else "",
                    "rates_stocks": bool(inst and inst.get("ratings")),
                    "status": status,
                    "shares_now": shares_now,
                    "shares_prev": shares_prev,
                    "shares_delta": shares_now - shares_prev,
                    "value_now": value_now,
                    "value_prev": value_prev,
                    "value_delta": value_now - value_prev,
                    "shares_common_now": now["shares_common"] if now else 0,
                    "shares_common_prev": before["shares_common"] if before else 0,
                }
            )
        records.sort(key=lambda d: -max(d["value_now"], d["value_prev"]))

        counts = Counter(d["status"] for d in records)
        wl = [d for d in records if d["watchlist"]]
        wl_now = [d for d in wl if d["value_now"] > 0]
        wl_prev = [d for d in wl if d["value_prev"] > 0]
        wl_shares_delta = sum(d["shares_delta"] for d in wl)
        wl_value_delta = sum(d["value_delta"] for d in wl)
        wl_rated_now = sum(1 for d in wl_now if d["rates_stocks"])
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
        breakdown: dict[str, Any] = get_institutional_breakdown(sym, no_cache=no_cache) if sym else {}
        shares_out = quote.get("shares_outstanding")
        # % Out numerators use COMMON shares (option legs excluded)
        wl_common_now = sum(d["shares_common_now"] for d in wl)
        wl_common_prev = sum(d["shares_common_prev"] for d in wl)
        all_common_now = sum(d["shares_common_now"] for d in records)
        all_common_prev = sum(d["shares_common_prev"] for d in records)
        wl_pct_now = (wl_common_now / shares_out * 100) if shares_out else None
        wl_pct_prev = (wl_common_prev / shares_out * 100) if shares_out else None
        all_pct_now = (all_common_now / shares_out * 100) if shares_out else None
        all_pct_prev = (all_common_prev / shares_out * 100) if shares_out else None
        for d in records:
            d["pct_out"] = (d["shares_common_now"] / shares_out * 100) if shares_out else None

        if json:
            print_json(
                {
                    "cusip": cusip,
                    "year": year,
                    "quarter": quarter,
                    "prev_year": py,
                    "prev_quarter": pq,
                    "prev_data": prev_available,
                    "rows_dropped": {"now": cur_dropped, "prev": prev_dropped},
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
                        "ratings_desks_now": wl_rated_now,
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
                    "yahoo_holders": breakdown,
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
            f"Watchlist: {len(wl_now)} holders now (prev {len(wl_prev)}; "
            f"{wl_rated_now} with ratings desks) · "
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
                f"Watchlist % Out (common shs): {wl_pct_now:.2f}% now vs {wl_pct_prev:.2f}% prev "
                f"([{'green' if delta_pp >= 0 else 'red'}]{delta_pp:+.2f}pp[/])"
            )
        if all_pct_now is not None and all_pct_prev is not None:
            delta_pp = all_pct_now - all_pct_prev
            lines.append(
                f"All listed % Out (common shs): {all_pct_now:.2f}% now vs {all_pct_prev:.2f}% prev "
                f"([{'green' if delta_pp >= 0 else 'red'}]{delta_pp:+.2f}pp[/])"
            )
        if breakdown.get("pct_institutions") is not None:
            # Yahoo's own snapshot, for reference against the 13F-derived % Out above.
            # Different basis (all ownership sources, current date) so it usually reads
            # higher than the 13F floor; see README "Data caveats".
            yh = f"Yahoo % Held by Institutions: [bold]{breakdown['pct_institutions'] * 100:.2f}%[/bold]"
            if breakdown.get("pct_institutions_float") is not None:
                yh += f" (of float {breakdown['pct_institutions_float'] * 100:.2f}%)"
            if breakdown.get("institutions_count"):
                yh += f" · {breakdown['institutions_count']:,} institutions"
            if breakdown.get("pct_insiders") is not None:
                yh += f" · insiders {breakdown['pct_insiders'] * 100:.2f}%"
            yh += " [dim](snapshot, today)[/dim]"
            lines.append(yh)
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

        # regroup by status: buyers together, sellers together (unchanged opt-in)
        groups = [
            ("INCREASED / NEW", ("NEW", "INCREASED")),
            ("REDUCED / CLOSED", ("REDUCED", "CLOSED")),
        ]
        if all:
            groups.append(("UNCHANGED", ("UNCHANGED",)))
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


def _history_row_dict(r: list) -> dict[str, Any]:
    """Named-field dict for a raw 13f.info history row (agent-friendly JSON)."""
    return {
        "period_end": r[0][0],
        "filing": r[0][1],
        "value_thousands": r[1],
        "pct_portfolio": r[2],
        "shares": r[3],
        "put_call": r[4],
        "filing_date": r[5],
        "year": r[6][0] if r[6] else None,
        "quarter": r[6][1] if r[6] else None,
    }


@app.command
def history(
    cik: Annotated[str, Parameter(help="Manager CIK (digits; zero-padding handled).")],
    cusip: Annotated[str, Parameter(help="9-char CUSIP, e.g. 172573107 for CRCL.")],
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """One manager's position history in one stock.

    --json prints ALL rows with named fields; --limit only affects the table.
    """

    def _go() -> None:
        data = get_json(f"{THIRTEENF_BASE}/data/manager/{cik}/cusip/{cusip}", no_cache=no_cache)
        # rows: [[period_end, filing_slug], value_thousands, pct, shares, put_call,
        #        filing_date, [year, quarter]]
        rows = data.get("data", [])
        if json:
            print_json([_history_row_dict(r) for r in rows])
            return
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


# --- evolution (institutional ownership over time) -------------------------


def _quarters_back(n: int) -> list[tuple[int, int]]:
    """Last `n` calendar quarters, oldest first, as (year, quarter)."""
    import datetime as _dt

    today = _dt.date.today()
    year, quarter = today.year, (today.month - 1) // 3 + 1
    out: list[tuple[int, int]] = []
    for _ in range(n):
        out.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return list(reversed(out))


def _quarter_end(year: int, quarter: int) -> str:
    """ISO date of a quarter end (13F report period)."""
    month = quarter * 3
    return f"{year}-{month:02d}-{30 if month in (6, 9) else 31}"


@app.command
def evolution(
    cusip: Annotated[str, Parameter(help="9-char CUSIP, e.g. 172573107 for CRCL.")],
    quarters: Annotated[
        int, Parameter(name="--quarters", help="How many recent quarters to walk back.")
    ] = 8,
    symbol: Annotated[
        Optional[str],
        Parameter(name="--symbol", help="Ticker symbol (auto-resolved via 13f.info when omitted)."),
    ] = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Institutional ownership of ONE stock over time, rebuilt from 13F filings.

    Yahoo's '% Held by Institutions' is a snapshot with no history, so each
    quarter is recomputed here: 13F-reported COMMON shares summed across all
    filers / shares outstanding in force at that quarter end. Amendments
    supersede originals and filer unit errors are dropped (Drop column).

    13F only covers managers over $100M AUM, so the series is a FLOOR and
    reads below Yahoo's snapshot (shown for reference). Trust the trend, not
    the level. One HTTP call per quarter, cached 24h.
    """

    def _go() -> None:
        if quarters < 1:
            err_console.print("[red]Error:[/red] --quarters must be >= 1")
            raise SystemExit(2)

        periods = _quarters_back(quarters)
        sym = symbol.strip().upper() if symbol else None
        issuer = None
        resolved_sym, issuer = _resolve_cusip_info(cusip, no_cache=no_cache)
        sym = sym or resolved_sym

        # denominator history: fetch from a bit before the first quarter end so
        # the oldest period still finds a share count at or before it
        shares_hist: dict[str, int] = {}
        if sym:
            first_end = _quarter_end(*periods[0])
            start = f"{int(first_end[:4]) - 1}{first_end[4:]}"
            shares_hist = get_shares_history(sym, start, no_cache=no_cache)

        rows: list[dict[str, Any]] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=err_console,
            transient=True,
        ) as progress:
            task = progress.add_task("quarters", total=len(periods))
            for year, quarter in periods:
                progress.update(task, description=f"{year} Q{quarter}")
                agg = _aggregate_13f(cusip, year, quarter, no_cache=no_cache)
                progress.advance(task)
                if not agg["filers"] or not agg["common_shares"]:
                    continue  # quarter not filed yet, or no common-share position
                end = _quarter_end(year, quarter)
                shares_out = shares_asof(shares_hist, end) if shares_hist else None
                rows.append(
                    {
                        "period": f"{year}Q{quarter}",
                        "year": year,
                        "quarter": quarter,
                        "period_end": end,
                        "filers": agg["filers"],
                        "rows_dropped": agg["rows_dropped"],
                        "common_shares": agg["common_shares"],
                        "shares_outstanding": shares_out,
                        "pct_out": (agg["common_shares"] / shares_out * 100) if shares_out else None,
                        "value_thousands": agg["value_thousands"],
                    }
                )

        if not rows:
            err_console.print(
                f"[yellow]No 13F data on 13f.info for {cusip} in the last {quarters} quarters.[/yellow]"
            )
            raise SystemExit(1)

        # pp change vs the previous reported quarter
        prev_pct: Optional[float] = None
        for r in rows:
            r["pct_out_delta_pp"] = (
                None if (prev_pct is None or r["pct_out"] is None) else r["pct_out"] - prev_pct
            )
            if r["pct_out"] is not None:
                prev_pct = r["pct_out"]

        breakdown = get_institutional_breakdown(sym, no_cache=no_cache) if sym else {}

        if json:
            print_json(
                {
                    "cusip": cusip,
                    "symbol": sym,
                    "issuer": issuer,
                    "quarters_requested": quarters,
                    "yahoo_holders": breakdown,
                    "history": rows,
                }
            )
            return

        render_table(
            f"Institutional ownership over time — {issuer or '-'} ({sym or '-'}) — {cusip}",
            ["Period", "Period End", "Filers", "Drop", "13F Common Shs", "Shares Out", "% Out", "Δ pp", "Value ($000)"],
            (
                [
                    r["period"],
                    r["period_end"],
                    fmt_int(r["filers"]),
                    fmt_int(r["rows_dropped"]),
                    fmt_int(r["common_shares"]),
                    fmt_int(r["shares_outstanding"]),
                    f"{r['pct_out']:.2f}%" if r["pct_out"] is not None else "-",
                    (
                        f"[{'green' if r['pct_out_delta_pp'] >= 0 else 'red'}]"
                        f"{r['pct_out_delta_pp']:+.2f}[/]"
                        if r["pct_out_delta_pp"] is not None
                        else ""
                    ),
                    fmt_usd_thousands(r["value_thousands"]),
                ]
                for r in rows
            ),
        )

        first, last = rows[0], rows[-1]
        if first["pct_out"] is not None and last["pct_out"] is not None and len(rows) > 1:
            swing = last["pct_out"] - first["pct_out"]
            console.print(
                f"[bold]{first['period']} → {last['period']}:[/bold] "
                f"{first['pct_out']:.2f}% → {last['pct_out']:.2f}% "
                f"([{'green' if swing >= 0 else 'red'}]{swing:+.2f}pp[/]) · "
                f"filers {first['filers']:,} → {last['filers']:,}"
            )
        if breakdown.get("pct_institutions") is not None:
            console.print(
                f"Yahoo % Held by Institutions today: "
                f"[bold]{breakdown['pct_institutions'] * 100:.2f}%[/bold] "
                f"[dim](snapshot; 13F series above is a floor — different basis)[/dim]"
            )
        if not shares_hist:
            err_console.print(
                "[dim]no shares-outstanding history from Yahoo — % Out unavailable "
                "(pass --symbol, or retry: yfinance rate-limits)[/dim]"
            )

    _run(_go)


@app.command
def filings(
    cik: str,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Recent 13F filings for a CIK from SEC EDGAR (external_id pipes into filing/compare)."""

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


def _latest_two_periods(cik: str, *, no_cache: bool = False) -> Optional[tuple[str, str, str]]:
    """(new_eid, old_eid, new_period) for the 2 most recent report periods of a CIK.

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
    return (
        best[periods[0]][1].replace("-", ""),
        best[periods[1]][1].replace("-", ""),
        periods[0],
    )


def _period_year_quarter(period: str) -> Optional[tuple[int, int]]:
    """'2026-06-30' -> (2026, 2). None on unparseable input."""
    try:
        year, month, _ = (int(p) for p in period.split("-"))
        return year, (month - 1) // 3 + 1
    except (ValueError, AttributeError):
        return None


def _shares_outstanding_split(
    cusip: str, year: int, quarter: int, *, no_cache: bool = False
) -> tuple[int, int]:
    """(watchlist_shares, all_shares) held in a CUSIP for one quarter.

    `shares` sums all rows (exposure, incl. option legs); the returned totals
    are COMMON shares only (option legs excluded) — the right numerator for
    % of shares outstanding.
    """
    data = get_json(f"{THIRTEENF_BASE}/data/cusip/{cusip}/{year}/{quarter}", no_cache=no_cache)
    by_cik = _holders_by_cik(data.get("data", []) or [])
    all_shares = sum(e["shares_common"] for e in by_cik.values())
    wl_shares = sum(e["shares_common"] for c, e in by_cik.items() if c in _WATCHLIST_BY_CIK)
    return wl_shares, all_shares


@app.command
def consensus(
    category: Annotated[str, Parameter(name="--category", help="Watchlist category (see `13f institutions`) or 'all'.")] = "all",
    ciks: Annotated[Optional[str], Parameter(name="--ciks", help='Comma-separated CIKs, e.g. "0001,0002" (overrides watchlist).')] = None,
    min_funds: Annotated[int, Parameter(name="--min-funds", help="Min distinct funds reporting a CUSIP.")] = 2,
    enrich: Annotated[int, Parameter(name="--enrich", help="Enrich top N rows (symbol + yfinance % outstanding). 0 disables.")] = 15,
    hub: Annotated[bool, Parameter(name="--hub", help="Keep only stocks covered by the Deep Dives Hub (ddq).")] = False,
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Aggregate quarter-over-quarter 13F moves across the watchlist by CUSIP.

    The 'R' column counts currently-holding funds that run sell-side ratings
    desks — a conflict-of-interest flag (ratings vs. positioning). --hub keeps
    only Deep-Dives-Hub-covered names (resolve with `ddq dd <TICKER>`).
    Positions are classified by SHARE delta, same as `position`.
    """

    def _go() -> None:
        cat = category.lower()
        if cat != "all" and cat not in categories():
            err_console.print(
                f"[red]Error:[/red] --category must be one of: all, {', '.join(categories())} — got '{category}'"
            )
            raise SystemExit(2)
        label = cat
        if ciks:
            institutions = [
                {"name": c.strip(), "cik": c.strip().zfill(10), "category": "custom", "ratings": False}
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
            # b+c: per CIK, latest 2 periods -> Change objects
            per_fund: dict[str, list[Change]] = {}
            latest_periods: list[str] = []
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
                    changes = _compare_changes(pair[0], pair[1], no_cache=no_cache)
                except FetchError as exc:
                    err_console.print(f"[yellow]skip {cik} ({inst['name']}): {exc}[/yellow]")
                    progress.advance(task)
                    continue
                per_fund[cik] = changes
                latest_periods.append(pair[2])
                progress.advance(task)

        if not per_fund:
            err_console.print("[red]Error:[/red] no compare data for any CIK in the set")
            raise SystemExit(1)

        # ratings-desk lookup covers custom CIKs too when they are watchlist members
        ratings_of = {inst["cik"]: _RATINGS_BY_CIK.get(inst["cik"], bool(inst.get("ratings"))) for inst in institutions}

        # d: aggregate by CUSIP across funds (share-based status, like `position`)
        agg: dict[str, dict[str, Any]] = {}
        for cik, changes in per_fund.items():
            for c in changes:
                cusip = c.cusip
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
                        "ratings_holding": set(),
                        "value_now": 0,
                        "value_delta": 0,
                        "shares_now": 0,
                    },
                )
                if c.issuer:
                    e["issuers"][c.issuer] += 1
                if e["symbol"] is None and c.symbol:
                    e["symbol"] = c.symbol
                e["funds"].add(cik)
                if c.status == "new":
                    e["new"].add(cik)
                elif c.status == "increased":
                    e["inc"].add(cik)
                elif c.status == "reduced":
                    e["red"].add(cik)
                elif c.status == "closed":
                    e["closed"].add(cik)
                if c.holds_after:
                    e["holding_now"].add(cik)
                    if ratings_of.get(cik):
                        e["ratings_holding"].add(cik)
                    e["value_now"] += c.value_after
                    e["shares_now"] += c.shares_after
                e["value_delta"] += c.value_delta

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
                    "n_ratings_funds_holding": len(e["ratings_holding"]),
                    "sum_value_now": e["value_now"],
                    "sum_value_delta": e["value_delta"],
                    "sum_shares_now": e["shares_now"],
                    "net_funds": len(e["new"]) + len(e["inc"]) - len(e["red"]) - len(e["closed"]),
                    "sector": None,
                    "market_cap": None,
                    "pct_out_watchlist": None,
                    "pct_out_all": None,
                    "pct_out_source": None,
                }
            )
        results.sort(key=lambda d: (-d["net_funds"], -d["sum_value_delta"]))

        # e2: optional Deep Dives Hub filter — keeps only hub-covered CUSIPs.
        # Hub membership is checked by CUSIP (the ticker->CUSIP mapping is
        # precomputed once and cached 7 days), so this is O(1) per row.
        if hub:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=err_console,
            ) as progress:
                task = progress.add_task("hub cusips", total=None)
                covered = hub_cusips(
                    no_cache=no_cache,
                    progress=lambda t: progress.update(task, description=f"hub cusips: {t}"),
                )
            err_console.print(f"[dim]deep-dives hub covers {len(covered)} CUSIPs[/dim]")
            for d in results:
                if d["cusip"] in covered:
                    d["hub"] = True
            results = [d for d in results if d.get("hub")]

        # most common latest report period across funds -> quarter for the
        # per-CUSIP holders endpoint (same data path `position` uses)
        mode_period = Counter(p for p in latest_periods if p).most_common(1)
        hq = _period_year_quarter(mode_period[0][0]) if mode_period else None

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
                        if shares_out and hq:
                            try:
                                wl_sh, all_sh = _shares_outstanding_split(
                                    d["cusip"], hq[0], hq[1], no_cache=no_cache
                                )
                                d["pct_out_watchlist"] = wl_sh / shares_out * 100
                                d["pct_out_all"] = all_sh / shares_out * 100
                                d["pct_out_source"] = "holders"
                            except FetchError:
                                # fall back to compare-row share sums (watchlist funds only)
                                d["pct_out_watchlist"] = d["sum_shares_now"] / shares_out * 100
                                d["pct_out_source"] = "compare"
                    progress.advance(task)

        if json:
            print_json(results)
            return

        shown = results[:limit] if limit else results
        err_console.print(
            f"[dim]{len(per_fund)}/{len(institutions)} funds · {len(agg)} CUSIPs · "
            f"{len(results)} pass --min-funds {min_funds}"
            + (f" · holders period {mode_period[0][0]}" if mode_period else "")
            + "[/dim]"
        )
        render_table(
            f"Consensus — {label} ({len(shown)} of {len(results)} rows)",
            ["Symbol", "Issuer", "CUSIP", "Funds", "NEW", "INC", "RED", "CLS", "Net", "Hold", "R", "Val Now ($000)", "Val Δ ($000)", "WL %Out", "All %Out"],
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
                    f"[yellow]{d['n_ratings_funds_holding']}[/yellow]" if d["n_ratings_funds_holding"] else "0",
                    fmt_usd_thousands(d["sum_value_now"]),
                    f"[{'green' if d['sum_value_delta'] >= 0 else 'red'}]{fmt_usd_thousands(d['sum_value_delta'])}[/]",
                    f"{d['pct_out_watchlist']:.2f}%" if d["pct_out_watchlist"] is not None else "-",
                    f"{d['pct_out_all']:.2f}%" if d["pct_out_all"] is not None else "-",
                ]
                for d in shown
            ),
        )

    _run(_go)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
