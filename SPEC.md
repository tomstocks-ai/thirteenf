# SPEC — thirteenf-cli (v0)

Python CLI that wraps 13f.info's JSON data API + SEC EDGAR submissions API.
No 13F XML parsing. Single focused tool, ~300-500 lines total.

## Location & layout
Create everything under `/mnt/agents/output/thirteenf-cli/`:
```
thirteenf-cli/
├── pyproject.toml          # deps: cyclopts, httpx, rich
├── README.md               # short usage doc
└── thirteenf/
    ├── __init__.py
    ├── __main__.py         # allows `python -m thirteenf`
    ├── cli.py              # cyclopts App, command definitions
    ├── client.py           # HTTP layer (throttle + cache + UA)
    ├── watchlist.py        # built-in institution watchlist
    └── render.py           # rich tables + --json passthrough
```

## CLI: cyclopts `App(name="13f_info")`, console script `thirteenf`
Global option on every command: `--json` (print raw JSON instead of rich tables).

### Commands
1. `institutions` — print the built-in watchlist (name, CIK, category: "biotech" | "megafund"). No network.
2. `search <query>` — GET `https://13f.info/data/autocomplete?q={query}` → two tables: managers (name, location, url→CIK) and cusips/companies (issuer, symbol, cusip).
3. `holdings <external_id>` — GET `https://13f.info/data/13f/{external_id}` → aggregated holdings table. Introspect the actual JSON shape and map columns sensibly.
4. `compare <external_id> <other_external_id>` — GET `https://13f.info/data/13f/{external_id}/compare/{other_external_id}`.
   Verified row shape (13 fields):
   `[symbol, issuer_name, class_title, cusip, put_call, shares_before, shares_after, shares_delta, shares_delta_pct, value_before, value_after, value_delta, value_delta_pct]`
   (values in $thousands, per 13F convention; symbol may be null). Default sort: value_delta_pct desc; show top 50 unless `--limit`.
5. `holders <cusip> --year YYYY --quarter Q` — GET `https://13f.info/data/cusip/{cusip}/{year}/{quarter}` → all managers holding that CUSIP. Verified row shape:
   `[[manager_name, cik, cusip], [period_end_date, filing_slug], shares, value, ...]` — introspect for extra fields. Sort by value desc.
6. `history <cik> <cusip>` — GET `https://13f.info/data/manager/{cik}/cusip/{cusip}` → one manager's position history in one stock. Introspect shape.
7. `filings <cik>` — GET `https://data.sec.gov/submissions/CIK{cik:0>10}.json`, filter recent filings to forms starting with `13F`; columns: form, filing_date, report_date, accession number, and the 13f.info `external_id` (accession number with dashes removed) so it can be piped straight into `holdings`/`compare`. Note in output when an entry is an amendment (`13F-HR/A`).

## HTTP layer (client.py)
- `httpx`, timeout 30s, retries: 2 on 5xx.
- User-Agent: `thirteenf-cli/0.1 (research tool; contact: user@example.com)` — REQUIRED by SEC for data.sec.gov; also send to 13f.info.
- Throttle: min 1.0s between requests to the same host (politeness).
- File cache: `~/.cache/thirteenf/`, key = sha256 of full URL, TTL default 24h for 13f.info data endpoints, 1h for EDGAR submissions. `--no-cache` flag bypasses read (still writes).
- Clean errors: 404 → "filing/CUSIP not found or not yet processed on 13f.info"; never dump raw tracebacks to the user.

## Watchlist (watchlist.py)
Category "biotech": RA Capital Management, Perceptive Advisors, Deerfield Management, Baker Bros Advisors, Orbimed Advisors, Redmile Group, Cormorant Asset Management, Avoro Capital, Frazier Life Sciences, EcoR1 Capital, Casdin Capital, Rock Springs Capital, Boxer Capital.
Category "megafund": Citadel Advisors, Morgan Stanley (CIK 0000895421), ARK Investment Management, Berkshire Hathaway (0001067983), JPMorgan Chase (0000019617), BlackRock, Vanguard Group, State Street.
CIKs: where known use them; otherwise put a best-guess CIK and VERIFY during testing via the `search` command / EDGAR — correct any that are wrong before delivery. Every entry must resolve to the right institution.

## Testing (mandatory before delivery)
`pip install -e .` then run live:
1. `thirteenf institutions`
2. `thirteenf search morgan` and `thirteenf search apple`
3. `thirteenf compare 000093583626000418 000204572426000008 --limit 10` (known-good)
4. `thirteenf holders 037833100 --year 2026 --quarter 2 --limit 10` (Apple)
5. `thirteenf filings 0000895421` (Morgan Stanley)
6. `thirteenf holdings <an external_id from step 5 output> --limit 5`
7. `thirteenf history 0001067983 037833100` (Berkshire/Apple)
8. `thirteenf search morgan --json` (JSON mode sanity)
All must succeed and produce sane output. Fix issues until they do.

## Explicitly out of scope (v0)
- OpenFIGI CUSIP→ticker enrichment (leave a TODO note in README)
- Cohort/consensus aggregation across managers (v1)
- Self-hosting the Rails app
