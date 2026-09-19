"""Best-effort Yahoo Finance enrichment via yfinance (optional).

yfinance rate-limits and breaks often, so EVERYTHING here degrades gracefully:
failures return empty/partial dicts instead of raising. yfinance is imported
lazily and manages its own HTTP. Results are cached on disk for 24h.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from thirteenf.client import CACHE_DIR

YF_TTL_SECONDS = 24 * 3600


def _cache_path(symbol: str, kind: str = "") -> Path:
    suffix = f"_{kind}" if kind else ""
    return CACHE_DIR / f"yf_{symbol}{suffix}.json"


def _read_cache(symbol: str, kind: str = "") -> dict[str, Any] | None:
    path = _cache_path(symbol, kind)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - payload.get("fetched_at", 0) > YF_TTL_SECONDS:
        return None
    body = payload.get("body")
    return body if isinstance(body, dict) else None


def _write_cache(symbol: str, body: dict[str, Any], kind: str = "") -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(symbol, kind).write_text(
            json.dumps({"fetched_at": time.time(), "body": body})
        )
    except OSError:
        pass  # caching is best-effort


def _yfinance() -> Any:
    """Import yfinance lazily with its logger muted. None when unavailable."""
    try:
        import logging

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        import yfinance as yf
    except Exception:
        return None
    return yf


def _fi_get(fast_info: Any, key: str) -> Any:
    """Safe access into yfinance's fast_info (lazy, raises on rate-limit)."""
    try:
        return fast_info[key]
    except Exception:
        return None


def get_quote(symbol: str, *, no_cache: bool = False) -> dict[str, Any]:
    """Best-effort profile/quote for a ticker symbol. Never raises.

    Prefers ``Ticker.fast_info`` (cheaper) and falls back to ``Ticker.info``.
    Returns {} when yfinance is unavailable, rate-limited, or the symbol is
    unknown.
    """
    symbol = symbol.upper().strip()
    if not symbol:
        return {}
    if not no_cache:
        cached = _read_cache(symbol)
        if cached is not None:
            return cached

    yf = _yfinance()
    if yf is None:
        return {}

    data: dict[str, Any] = {}
    try:
        ticker = yf.Ticker(symbol)
        try:
            fi = ticker.fast_info
            data["last_price"] = _fi_get(fi, "last_price")
            data["market_cap"] = _fi_get(fi, "market_cap")
            data["shares_outstanding"] = _fi_get(fi, "shares")
            data["year_high"] = _fi_get(fi, "year_high")
            data["year_low"] = _fi_get(fi, "year_low")
            data["avg_volume"] = _fi_get(fi, "three_month_average_volume")
        except Exception:
            pass
        try:
            info = ticker.info
        except Exception:
            info = None
        if isinstance(info, dict):
            data["name"] = info.get("longName") or info.get("shortName")
            data["sector"] = info.get("sector")
            data["industry"] = info.get("industry")
            data["float_shares"] = info.get("floatShares")
            data["implied_shares_outstanding"] = info.get("impliedSharesOutstanding")
            # fallbacks for anything fast_info missed
            for key, info_key in (
                ("last_price", "currentPrice"),
                ("market_cap", "marketCap"),
                ("shares_outstanding", "sharesOutstanding"),
                ("year_high", "fiftyTwoWeekHigh"),
                ("year_low", "fiftyTwoWeekLow"),
                ("avg_volume", "averageVolume"),
            ):
                if data.get(key) is None:
                    data[key] = info.get(info_key)
            # shares_outstanding definition: prefer IMPLIED (all share classes,
            # e.g. GOOG+GOOGL, BRK.A+B) over the single-filing reported count —
            # it is the denominator Yahoo itself uses for multi-class market cap.
            if data.get("implied_shares_outstanding"):
                data["shares_outstanding"] = data["implied_shares_outstanding"]
    except Exception:
        return {}

    data = {k: v for k, v in data.items() if v is not None}
    if data:
        _write_cache(symbol, data)
    return data


def get_institutional_breakdown(symbol: str, *, no_cache: bool = False) -> dict[str, Any]:
    """Yahoo's majorHoldersBreakdown for a symbol. Never raises.

    This is the '% Held by Institutions' figure shown on Yahoo's holders page.
    It is a SNAPSHOT: Yahoo overwrites it and exposes no history, which is why
    `13f evolution` reconstructs a time series from 13F filings instead.

    Returns fractions (0.68394, not 68.394) or {} when Yahoo doesn't cooperate.
    """
    symbol = symbol.upper().strip()
    if not symbol:
        return {}
    if not no_cache:
        cached = _read_cache(symbol, "holders")
        if cached is not None:
            return cached

    yf = _yfinance()
    if yf is None:
        return {}

    try:
        df = yf.Ticker(symbol).get_major_holders()
        if df is None or df.empty:
            return {}
        raw = df[df.columns[0]].to_dict()
    except Exception:
        return {}

    def _val(key: str) -> float | None:
        try:
            v = raw.get(key)
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    count = _val("institutionsCount")
    data = {
        "pct_institutions": _val("institutionsPercentHeld"),
        "pct_institutions_float": _val("institutionsFloatPercentHeld"),
        "pct_insiders": _val("insidersPercentHeld"),
        "institutions_count": None if count is None else int(count),
    }
    data = {k: v for k, v in data.items() if v is not None}
    if data:
        _write_cache(symbol, data, "holders")
    return data


def get_shares_history(symbol: str, start: str, *, no_cache: bool = False) -> dict[str, int]:
    """Shares-outstanding history as {ISO date: shares}. Never raises.

    Backs the denominator of `13f evolution`, so each quarter is divided by the
    share count in force THEN rather than today's.
    """
    symbol = symbol.upper().strip()
    if not symbol:
        return {}
    cache_key = f"shares_{start}"
    if not no_cache:
        cached = _read_cache(symbol, cache_key)
        if cached is not None:
            return {k: int(v) for k, v in cached.items()}

    yf = _yfinance()
    if yf is None:
        return {}

    try:
        series = yf.Ticker(symbol).get_shares_full(start=start)
        if series is None or len(series) == 0:
            return {}
        series = series[~series.index.duplicated(keep="last")].sort_index()
        data = {ts.date().isoformat(): int(v) for ts, v in series.items()}
    except Exception:
        return {}

    if data:
        _write_cache(symbol, data, cache_key)
    return data


def shares_asof(history: dict[str, int], when: str) -> int | None:
    """Last known shares outstanding at or before ISO date `when`."""
    dates = [d for d in history if d <= when]
    return history[max(dates)] if dates else None
