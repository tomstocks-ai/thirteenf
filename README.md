# thirteenf

A command-line tool for researching SEC 13F filings: what institutions own,
and how their positions change quarter over quarter. It wraps the 13f.info
JSON data API and the SEC EDGAR submissions API — no 13F XML parsing.

The built-in watchlist covers the ~100 largest 13F filers, ranked by latest
reported holdings value and split into 10 categories (index, assetmgr, bank,
quant, hedge, tiger, activist, pension, insurance, biotech). Institutions
whose affiliates publish sell-side analyst ratings (Morgan Stanley, JPMorgan,
Mizuho, Goldman Sachs, ...) carry a `ratings` flag, surfaced wherever they
appear — useful for spotting positions that move against an institution's own
published ratings.

## Install

Requires Python >= 3.10.

```bash
pip install -e .
```

This gives you the `13f` command (`python -m thirteenf` works too).

## The 3 research chains

### 1. Institution deep-dive

```bash
13f search situational                      # find the manager, get its CIK
13f filings 0002045724                      # recent 13F filings, with external_ids
13f filing 000119312526352200               # every position in ONE filing
13f compare <new_id> <old_id>               # position-by-position changes, QoQ
```

`filings` prints an `external_id` column (the SEC accession number without
dashes) ready to paste into `filing` or `compare`.

### 2. Stock holders

```bash
13f search CRCL                             # find the CUSIP for a ticker/name
13f holders 172573107 2026 2 --limit 50     # top 50 managers holding it in 2026 Q2
13f position 172573107 2026 2               # QoQ holder consensus for one stock
```

`holders` prints a totals footer and, when it can resolve a ticker (or you
pass `--symbol CRCL`), the listed managers' combined % of shares outstanding
via Yahoo Finance. `position` compares two quarters per manager: holders
regrouped into INCREASED/NEW and REDUCED/CLOSED tables (`--all` adds
UNCHANGED), watchlist badges (e.g. `BANK·R` = bank with a ratings desk), and
totals / % of shares outstanding for both the watchlist and ALL listed
managers.

### 3. Consensus scan

```bash
13f consensus --category hedge --min-funds 2
13f consensus --category all --min-funds 5 --enrich 20
```

Aggregates the latest two 13F filings of every fund in the built-in watchlist
(101 institutions) into one table: which CUSIPs the smart money is
collectively buying or exiting, ranked by `net_funds` (funds new + increased
− reduced − closed). The `R` column counts holders that run sell-side ratings
desks. `--category` accepts any watchlist category (see `13f institutions`)
or `all`; `--ciks` overrides the watchlist entirely. `--enrich N` (default 15)
recovers missing tickers via 13f.info and adds each CUSIP's watchlist-wide %
of shares outstanding via yfinance. A full-watchlist run makes ~200+ HTTP
calls (1s/host throttle, cached 24h), with progress on stderr — subsequent
runs are mostly cache hits.

## Command reference

| Command | Arguments | What it does |
| --- | --- | --- |
| `13f search` | `<query>` | Find managers (→ CIK) and companies (→ CUSIP) |
| `13f filings` | `<cik>` | Recent 13F filings from EDGAR; prints `external_id`s |
| `13f filing` | `<external_id> [--limit N]` | Positions reported in ONE filing (alias: `holdings`) |
| `13f compare` | `<new_id> <old_id> [--only new\|increased\|reduced\|closed] [--all] [--detailed]` | QoQ position changes: summary panel + split INCREASED/NEW vs DECREASED/CLOSED tables |
| `13f holders` | `<cusip> <year> <quarter> [--limit N] [--symbol T]` | All managers holding a CUSIP that quarter, with totals footer |
| `13f position` | `<cusip> <year> <quarter> [--symbol T] [--limit N] [--all]` | QoQ holder consensus for one ticker: INCREASED/NEW + REDUCED/CLOSED tables (`--limit` per group), watchlist + ratings-desk badges, totals and % of shares outstanding for the watchlist AND all listed managers |
| `13f history` | `<cik> <cusip> [--limit N]` | One manager's position in one stock over time |
| `13f consensus` | `[--category C\|all] [--ciks "0001,0002"] [--min-funds 2] [--enrich 15] [--limit N]` | Cross-fund aggregation of the latest QoQ moves |
| `13f ticker` | `<symbol>` | Quote & profile via yfinance (name, sector, market cap, shares outstanding, float, price, 52w range, avg volume) |
| `13f institutions` | `[--category C]` | The built-in watchlist, sorted by latest 13F value, with ratings-desk flags (no network) |

Global flags: `--json` on every command (see below), `--no-cache` (bypass
cache reads; still writes) on network commands.

## For agents

Every command supports `--json` with **named fields** (no positional arrays),
and `--limit` never truncates JSON output — JSON always contains all rows.
Errors go to stderr with exit code 1 (fetch/lookup failures) or 2 (bad
arguments); stdout stays clean, so `13f ... --json | jq ...` is safe.

Typical chaining recipes:

```bash
# CIK -> latest two filings -> what did they buy?
# (search returns all name matches — pick the intended one, don't assume [0])
CIK=$(13f search "bridgewater" --json | jq -r '.managers[] | select(.name | test("Associates")) | .url | split("/")[-1] | split("-")[0]')
IDS=$(13f filings $CIK --json | jq -r '[.[0].external_id, .[1].external_id] | @tsv')
13f compare $IDS --json | jq '[.[] | select(.status == "new")]'

# Who accumulates a stock, and do ratings desks hold it?
13f position 172573107 2026 2 --json \
  | jq '{watchlist, all, buyers: [.rows[] | select(.status == "NEW" or .status == "INCREASED") | {manager, shares_delta, rates_stocks}]}'

# Which watchlist institutions publish ratings?
13f institutions --json | jq '[.[] | select(.ratings)]'
```

JSON field reference: `filing` rows have
`symbol, issuer, class, cusip, value_thousands, pct_portfolio, shares, put_call`;
`compare` rows add `*_before/after/delta` (shares & value) plus a `status`
(`new|increased|reduced|closed|unchanged`); `position` rows have per-manager
shares/value deltas, `status` (uppercase), `watchlist` badge and
`rates_stocks`. All 13F money values are in **$thousands** per SEC convention.

## Data caveats

- **45-day lag.** 13Fs are due within 45 days of quarter end; you're always
  looking at positions up to ~4.5 months stale.
- **Long only.** 13Fs disclose long positions (and options) — shorts are not
  reported. A fund "closing" a position may have flipped short; you can't see it.
- **Splits distort share counts.** Compare value deltas, not raw share deltas,
  across split events.
- **Values are in $thousands**, per 13F convention (except `value_b` in the
  watchlist, which is $billions).
- **Trading-firm 13F values include options notional** (Susquehanna, Jane
  Street, Citadel...), which inflates them vs. long-only managers.
- Amendments (13F-HR/A) supersede originals; `consensus` uses the latest filing
  per report period.
- The `ratings` flag marks sell-side research publishers (or their parents).
  It is a conflict-of-interest *flag*, not an accusation: banks run Chinese
  walls, but a fund accumulating a stock its own analysts rate Sell is worth
  a second look.
- yfinance enrichment is best-effort and rate-limited often; blank cells mean
  Yahoo didn't cooperate, not that data doesn't exist.

## Credits

- Data: [13f.info](https://13f.info) by Todd Schneider, and the
  [SEC EDGAR](https://www.sec.gov/edgar) submissions API.
- Quotes/profiles: Yahoo Finance via yfinance.
