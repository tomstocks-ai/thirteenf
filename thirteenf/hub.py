"""Deep Dives Hub client — same data layer as ddq, riding thirteenf's cache.

Remote by default (GitHub Pages API). Set DEEP_DIVES_LOCAL=/path/to/docs/api
for offline use against a deep-dives-hub repo clone (mirrors ddq /
deep_dives_mcp LOCAL mode).

The hub index tracks TICKERS; thirteenf works in CUSIPs. hub_cusips() bridges
the two by resolving each hub ticker to its CUSIP(s) via 13f.info autocomplete
once, then caching the derived mapping for 7 days (the hub changes rarely).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from thirteenf.client import CACHE_DIR, THIRTEENF_BASE, FetchError, get_json

API = "https://tomstocks-ai.github.io/deep-dives-hub/api"
HUB_CUSIPS_TTL = 7 * 24 * 3600


def hub_index(*, no_cache: bool = False) -> list[dict[str, Any]]:
    """All hub-tracked tickers (the tickers.json master index)."""
    local = os.environ.get("DEEP_DIVES_LOCAL")
    if local:
        data = json.loads((Path(local) / "tickers.json").read_text())
    else:
        data = get_json(f"{API}/tickers.json", no_cache=no_cache)
    return data.get("tickers", [])


def hub_tickers(*, no_cache: bool = False) -> set[str]:
    """Uppercase ticker set covered by the Deep Dives Hub."""
    return {
        str(t.get("ticker", "")).upper()
        for t in hub_index(no_cache=no_cache)
        if t.get("ticker")
    }


def _resolve_ticker_cusips(ticker: str, *, no_cache: bool = False) -> set[str]:
    """CUSIP(s) for a hub ticker via 13f.info autocomplete ('TICKER - ISSUER' hits)."""
    try:
        data = get_json(f"{THIRTEENF_BASE}/data/autocomplete?q={ticker}", no_cache=no_cache)
    except FetchError:
        return set()
    out = set()
    for c in data.get("cusips", []):
        symbol, sep, _ = (c.get("name") or "").partition(" - ")
        if sep and symbol.strip().upper() == ticker.upper():
            cusip = (c.get("url") or "").rsplit("/", 1)[-1]
            if cusip:
                out.add(cusip)
    return out


def hub_cusips(
    *,
    no_cache: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> set[str]:
    """All CUSIPs covered by the hub (derived mapping, cached 7 days)."""
    path = CACHE_DIR / "hub_cusips.json"
    if not no_cache and path.exists():
        try:
            payload = json.loads(path.read_text())
            if time.time() - payload.get("fetched_at", 0) <= HUB_CUSIPS_TTL:
                return set(payload.get("cusips", []))
        except (json.JSONDecodeError, OSError):
            pass
    cusips: set[str] = set()
    for ticker in sorted(hub_tickers(no_cache=no_cache)):
        if progress:
            progress(ticker)
        cusips |= _resolve_ticker_cusips(ticker, no_cache=no_cache)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "cusips": sorted(cusips)}))
    except OSError:
        pass  # caching is best-effort
    return cusips
