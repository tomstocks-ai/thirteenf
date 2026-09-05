"""cyclopts App and command definitions for thirteenf-cli."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from cyclopts import App, Parameter

from thirteenf.client import EDGAR_BASE, THIRTEENF_BASE, FetchError, get_json
from thirteenf.render import (
    err_console,
    fmt_int,
    fmt_pct,
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
            cusips.append([issuer.strip(), symbol.strip(), cusip])
        render_table(f"CUSIPs matching '{query}'", ["Issuer", "Symbol", "CUSIP"], cusips)

    _run(_go)


def _manager_cik(url: str) -> str:
    # "/manager/0000895421-morgan-stanley" -> "0000895421"
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.split("-", 1)[0]


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


@app.command
def compare(
    external_id: str,
    other_external_id: str,
    limit: LimitOpt = None,
    json: JsonFlag = False,
    no_cache: NoCacheFlag = False,
) -> None:
    """Compare two 13F filings position-by-position (sorted by value delta % desc)."""

    def _go() -> None:
        eid, other = _external_id(external_id), _external_id(other_external_id)
        data = get_json(f"{THIRTEENF_BASE}/data/13f/{eid}/compare/{other}", no_cache=no_cache)
        if json:
            print_json(data)
            return
        # rows: [symbol, issuer, class, cusip, put_call, shares_before, shares_after,
        #        shares_delta, shares_delta_pct, value_before, value_after, value_delta, value_delta_pct]
        rows = sorted(data.get("data", []), key=lambda r: (r[12] is None, -(r[12] or 0)))
        rows = rows[: limit or 50]
        render_table(
            f"Compare {eid} vs {other}",
            [
                "Symbol", "Issuer", "Class", "CUSIP", "P/C",
                "Shrs Before", "Shrs After", "Shrs Δ", "Shrs Δ%",
                "Val Before", "Val After", "Val Δ", "Val Δ%",
            ],
            (
                [
                    trunc(r[0], 6) if r[0] else "-", trunc(r[1], 18), trunc(r[2], 12), r[3], r[4] or "-",
                    fmt_int(r[5]), fmt_int(r[6]), fmt_int(r[7]), fmt_pct(r[8]),
                    fmt_usd_thousands(r[9]), fmt_usd_thousands(r[10]),
                    fmt_usd_thousands(r[11]), fmt_pct(r[12]),
                ]
                for r in rows
            ),
        )

    _run(_go)


@app.command
def holders(
    cusip: str,
    year: Annotated[int, Parameter(name="--year")],
    quarter: Annotated[int, Parameter(name="--quarter")],
    limit: LimitOpt = None,
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
        padded = cik.strip().zfill(10)
        data = get_json(f"{EDGAR_BASE}/submissions/CIK{padded}.json", no_cache=no_cache)
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        records: list[dict[str, Any]] = []
        for i, form in enumerate(forms):
            if not form.startswith("13F"):
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
        if json:
            print_json(records)
            return
        render_table(
            f"13F filings — {data.get('name', padded)} ({padded})",
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
