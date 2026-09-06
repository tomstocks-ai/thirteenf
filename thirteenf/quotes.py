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


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"yf_{symbol}.json"


def _read_cache(symbol: str) -> dict[str, Any] | None:
    path = _cache_path(symbol)
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


def _write_cache(symbol: str, body: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(symbol).write_text(
            json.dumps({"fetched_at": time.time(), "body": body})
        )
    except OSError:
        pass  # caching is best-effort


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

    try:
        import logging

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        import yfinance as yf
    except Exception:
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
    except Exception:
        return {}

    data = {k: v for k, v in data.items() if v is not None}
    if data:
        _write_cache(symbol, data)
    return data
