# thirteenf

A command-line tool for researching SEC 13F filings: what institutions own,
and how their positions change quarter over quarter. It wraps the 13f.info
JSON data API and the SEC EDGAR submissions API — no 13F XML parsing.

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
13f compare <new_id> <old_id>               # position-by-position changes, QoQ
```

`filings` prints an `external_id` column (the SEC accession number without
dashes) ready to paste into `compare` or `holdings`.

### 2. Stock holders

```bash
13f search CRCL                             # find the CUSIP for a ticker/name
13f holders 172573107 2026 2 50             # top 50 managers holding it in 2026 Q2
```

`holders` prints a totals footer and, when it can resolve a ticker (or you
pass `--symbol CRCL`), the listed managers' combined % of shares outstanding
via Yahoo Finance.

### 3. Consensus scan

```bash
13f consensus --category biotech --min-funds 3
```

Aggregates the latest two 13F filings of every fund in the built-in watchlist
(13 biotech specialists + 8 megafunds) into one table: which CUSIPs the smart
money is collectively buying or exiting, ranked by `net_funds` (funds new +
increased − reduced − closed). `--enrich N` (default 15) recovers missing
tickers via 13f.info and adds each CUSIP's watchlist-wide % of shares
outstanding via yfinance. A full run makes ~50+ HTTP calls (1s/host throttle),
with progress on stderr.

## Command reference

| Command | Arguments | What it does |
| --- | --- | --- |
| `13f search` | `<query>` | Find managers (→ CIK) and companies (→ CUSIP) |
| `13f filings` | `<cik>` | Recent 13F filings from EDGAR; prints `external_id`s |
| `13f holdings` | `<external_id>` | Aggregated holdings of one filing |
| `13f compare` | `<new_id> <old_id>` | QoQ position changes: summary panel + split INCREASED/NEW vs DECREASED/CLOSED tables (`--all` includes unchanged, `--detailed` adds Class/Put-Call) |
| `13f holders` | `<cusip> <year> <quarter> [limit]` | All managers holding a CUSIP that quarter, with totals footer (`--symbol` for % of shares outstanding) |
| `13f position` | `<cusip> <year> <quarter> [--symbol T] [--limit N] [--all]` | QoQ holder consensus for one ticker: holders regrouped into INCREASED/NEW and REDUCED/CLOSED tables (`--limit` per group, `--all` adds UNCHANGED), watchlist badges, and totals + % of shares outstanding for both the watchlist and ALL listed managers |
| `13f history` | `<cik> <cusip>` | One manager's position in one stock over time |
| `13f consensus` | `[--category biotech\|megafund\|all] [--ciks "0001,0002"] [--min-funds 2] [--enrich 15] [--limit N]` | Cross-fund aggregation of the latest QoQ moves |
| `13f ticker` | `<symbol>` | Quote & profile via yfinance (name, sector, market cap, shares outstanding, float, price, 52w range, avg volume) |
| `13f institutions` | — | Print the built-in watchlist (no network) |

Global flags: `--json` (raw JSON instead of tables) on every command,
`--no-cache` (bypass cache reads; still writes) on network commands.

## Data caveats

- **45-day lag.** 13Fs are due within 45 days of quarter end; you're always
  looking at positions up to ~4.5 months stale.
- **Long only.** 13Fs disclose long positions (and options) — shorts are not
  reported. A fund "closing" a position may have flipped short; you can't see it.
- **Splits distort share counts.** Compare value deltas, not raw share deltas,
  across split events.
- **Values are in $thousands**, per 13F convention.
- Amendments (13F-HR/A) supersede originals; `consensus` uses the latest filing
  per report period.
- yfinance enrichment is best-effort and rate-limited often; blank cells mean
  Yahoo didn't cooperate, not that data doesn't exist.

## Credits

- Data: [13f.info](https://13f.info) by Todd Schneider, and the
  [SEC EDGAR](https://www.sec.gov/edgar) submissions API.
- Quotes/profiles: Yahoo Finance via yfinance.
