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
13f evolution 172573107 --quarters 8        # institutional ownership trend, 8 quarters
```

`holders` prints a totals footer and, when it can resolve a ticker (or you
pass `--symbol CRCL`), the listed managers' combined % of shares outstanding
via Yahoo Finance. `position` compares two quarters per manager: holders
regrouped into INCREASED/NEW and REDUCED/CLOSED tables (`--all` adds
UNCHANGED), watchlist badges (e.g. `BANK·R` = bank with a ratings desk), and
totals / % of shares outstanding for both the watchlist and ALL listed
managers. Its header also carries Yahoo's own **% Held by Institutions**
snapshot (plus % of float, institution count and insider %) so you can read
the 13F-derived figure against Yahoo's.

`evolution` answers "is institutional ownership rising or falling?". Yahoo
publishes % Held by Institutions only as a current snapshot, so the series is
rebuilt from the filings themselves: for each of the last `--quarters`
quarters, 13F-reported common shares summed across every filer, divided by the
shares outstanding in force at that quarter end.

```
Period   Period End   Filers  Drop   13F Common Shs   Shares Out     % Out    Δ pp
2025Q2   2025-06-30   254     5      79,288,320       241,379,008    32.85%
2025Q3   2025-09-30   344     7      89,067,876       237,894,810    37.44%   +4.59
2025Q4   2025-12-31   473     8      105,832,303      254,437,614    41.59%   +4.15
2026Q1   2026-03-31   547     3      118,469,728      265,480,606    44.62%   +3.03
2026Q2   2026-06-30   574     8      131,946,033      248,576,030    53.08%   +8.46
2025Q2 → 2026Q2: 32.85% → 53.08% (+20.23pp) · filers 254 → 574
Yahoo % Held by Institutions today: 68.39% (snapshot)
```

One HTTP call per quarter (1s throttle, cached 24h). The `Drop` column counts
rows excluded as superseded amendments or filer unit errors — see *Data
caveats*.

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
of shares outstanding via yfinance (one Yahoo call per row — that's why only
the top N get % Out; `--enrich 0` disables). A full-watchlist run makes ~200+
HTTP calls (1s/host throttle, cached 24h), with progress on stderr —
subsequent runs are mostly cache hits.

`--hub` keeps only stocks covered by the
[Deep Dives Hub](https://github.com/tomstocks-ai/deep-dives-hub) (the same
data layer `ddq dd` uses): the hub's tickers are resolved to CUSIPs once
(cached 7 days), so filtering itself is instant. Hub rows chain straight into
ddq:

## Command reference

| Command | Arguments | What it does |
| --- | --- | --- |
| `13f search` | `<query>` | Find managers (→ CIK) and companies (→ CUSIP) |
| `13f filings` | `<cik>` | Recent 13F filings from EDGAR; prints `external_id`s |
| `13f filing` | `<external_id> [--limit N]` | Positions reported in ONE filing (alias: `holdings`) |
| `13f compare` | `<new_id> <old_id> [--only new\|increased\|reduced\|closed] [--all] [--detailed]` | QoQ position changes: summary panel + split INCREASED/NEW vs DECREASED/CLOSED tables |
| `13f holders` | `<cusip> <year> <quarter> [--limit N] [--symbol T]` | All managers holding a CUSIP that quarter, with totals footer |
| `13f position` | `<cusip> <year> <quarter> [--symbol T] [--limit N] [--all]` | QoQ holder consensus for one ticker: INCREASED/NEW + REDUCED/CLOSED tables (`--limit` per group), watchlist + ratings-desk badges, totals and % of shares outstanding for the watchlist AND all listed managers, plus Yahoo's % Held by Institutions snapshot |
| `13f evolution` | `<cusip> [--quarters 8] [--symbol T]` | Institutional ownership of one stock over time, rebuilt from 13F filings: % of shares outstanding per quarter with pp deltas, against Yahoo's current snapshot |
| `13f history` | `<cik> <cusip> [--limit N]` | One manager's position in one stock over time |
| `13f consensus` | `[--category C\|all] [--ciks "0001,0002"] [--min-funds 2] [--enrich 15] [--hub] [--limit N]` | Cross-fund aggregation of the latest QoQ moves; `--hub` keeps only Deep-Dives-Hub-covered names |
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

# Is institutional ownership trending up? (pp change per quarter)
13f evolution 172573107 --json \
  | jq -r '.history[] | [.period, .pct_out, .pct_out_delta_pp] | @tsv'

# 13F-derived ownership vs Yahoo's snapshot, in one line
13f evolution 172573107 --json \
  | jq '{latest: .history[-1].pct_out, yahoo: (.yahoo_holders.pct_institutions * 100)}'

# Which watchlist institutions publish ratings?
13f institutions --json | jq '[.[] | select(.ratings)]'

# Smart-money moves limited to Deep-Dives-Hub names -> straight into ddq
13f consensus --hub --min-funds 3 --json | jq -r '.[].symbol' | sort -u \
  | xargs -I{} ddq dd {}
```

JSON field reference: `filing` rows have
`symbol, issuer, class, cusip, value_thousands, pct_portfolio, shares, put_call`;
`compare` rows add `*_before/after/delta` (shares & value) plus a `status`
(`new|increased|reduced|closed|unchanged`); `position` rows have per-manager
shares/value deltas, `status` (uppercase), `watchlist` badge and
`rates_stocks`, and the payload carries `yahoo_holders` (Yahoo's institutional
breakdown, as fractions). `evolution` returns `history[]` with
`period, period_end, filers, rows_dropped, common_shares, shares_outstanding,
pct_out, pct_out_delta_pp, value_thousands` plus the same `yahoo_holders`.
All 13F money values are in **$thousands** per SEC convention.

## Data caveats

- **45-day lag.** 13Fs are due within 45 days of quarter end; you're always
  looking at positions up to ~4.5 months stale.
- **Long only.** 13Fs disclose long positions (and options) — shorts are not
  reported. A fund "closing" a position may have flipped short; you can't see it.
- **Position changes are classified by SHARE delta, not value** (`new` /
  `increased` / `reduced` / `closed` in `compare`, `position`, `consensus`).
  A fund that sells shares into a rising price is REDUCED — price drift is
  never misread as conviction. Value columns are still shown for sizing.
- **Splits distort share counts.** Around split events, share-based
  classification can misfire; cross-check with the value columns.
- **Values are in $thousands**, per 13F convention (except `value_b` in the
  watchlist, which is $billions).
- **% of shares outstanding — definitions.** Numerator: 13F-reported COMMON
  shares summed across filers (put/call legs excluded — options are reported
  as underlying-equivalent shares and would double-count). Denominator:
  Yahoo's shares outstanding, preferring `impliedSharesOutstanding` (all
  share classes, e.g. GOOG+GOOGL) over the single-filing reported count.
  Yahoo's figure can lag recent issuance, so >100% is possible — when that
  happens the 13F numerator is the fresher signal.
- **Two denominators, on purpose.** `position` and `holders` divide by
  **today's** shares outstanding (what Yahoo reports now); `evolution` divides
  each quarter by the count **in force at that quarter end**
  (`get_shares_full`). So the two can disagree on the same quarter — CRCL
  2026Q2 reads 48.40% in `position` (272.6M shares out today) and 53.08% in
  `evolution` (248.6M then). Use `evolution` for trends, since a buyback or
  issuance would otherwise masquerade as an ownership change.
- **Superseded amendments are dropped.** A manager legitimately files several
  rows per CUSIP in ONE filing (share classes, option legs, sub-accounts) and
  those are summed. But a 13F-HR/A or restatement arrives under a higher
  accession number and *replaces* the original, so only each filer's latest
  accession is counted. Summing both would double-count: AAPL 2026Q2 has 6,514
  raw rows for 6,159 distinct filers.
- **Filer unit errors are filtered.** Rows whose implied price
  (value ÷ shares) is more than 10x off the cross-filer median are dropped as
  data-entry errors. CalSTRS reported 6,446,426,607 AAPL shares against $22.3B
  in 2026Q2 — value and shares transposed, an implied $3.46 against a ~$289
  median — which alone pushed the total above 100% of shares outstanding. The
  `Drop` column in `evolution` (and `rows_dropped` in JSON) reports the count,
  so the filtering is visible rather than silent.
- **Yahoo's % Held by Institutions is a snapshot, not a series.** Yahoo
  overwrites `majorHoldersBreakdown` and exposes no history — that's why
  `evolution` reconstructs the trend from filings. The two also differ in
  basis: Yahoo blends ownership sources beyond 13F and reports % of float
  alongside % outstanding, while the 13F series counts only managers above
  $100M AUM filing 13F-HR. Expect the 13F figure to sit **below** Yahoo's
  (CRCL: 53.08% for 2026Q2 vs Yahoo's 68.39% today) and read it as a floor.
  The most recent quarter also keeps rising as late filings arrive.
- `consensus` enrichment columns `WL %Out` / `All %Out` use the per-CUSIP
  holders endpoint (same data path as `position`) for the mode report quarter
  of the scanned funds — not the compare-row sums. `pct_out_source` in JSON
  says "holders" (accurate) or "compare" (fallback).
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
