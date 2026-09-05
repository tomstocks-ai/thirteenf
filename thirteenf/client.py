"""HTTP layer: httpx + throttle + file cache + clean errors."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = "thirteenf-cli/0.1 (research tool; contact: user@example.com)"
CACHE_DIR = Path.home() / ".cache" / "thirteenf"

THIRTEENF_BASE = "https://13f.info"
EDGAR_BASE = "https://data.sec.gov"

TTL_SECONDS = {
    "13f.info": 24 * 3600,  # 13f.info data endpoints
    "data.sec.gov": 3600,  # EDGAR submissions
}
DEFAULT_TTL = 24 * 3600
MIN_INTERVAL = 1.0  # seconds between requests to the same host

_last_request_at: dict[str, float] = {}


class FetchError(Exception):
    """User-facing fetch failure (never leak tracebacks)."""


def _ttl_for(url: str) -> int:
    host = urlparse(url).hostname or ""
    return TTL_SECONDS.get(host, DEFAULT_TTL)


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _read_cache(url: str) -> Any | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - payload.get("fetched_at", 0) > _ttl_for(url):
        return None
    return payload.get("body")


def _write_cache(url: str, body: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(url).write_text(
            json.dumps({"fetched_at": time.time(), "url": url, "body": body})
        )
    except OSError:
        pass  # caching is best-effort


def _throttle(url: str) -> None:
    host = urlparse(url).hostname or ""
    last = _last_request_at.get(host, 0.0)
    wait = MIN_INTERVAL - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def get_json(url: str, *, no_cache: bool = False) -> Any:
    """GET a JSON endpoint with cache, throttle, and retries. Returns parsed JSON."""
    if not no_cache:
        cached = _read_cache(url)
        if cached is not None:
            return cached

    last_exc: Exception | None = None
    for attempt in range(3):  # 1 try + 2 retries on 5xx
        try:
            _throttle(url)
            with httpx.Client(
                timeout=30.0, headers={"User-Agent": USER_AGENT}
            ) as client:
                resp = client.get(url)
            if resp.status_code == 404:
                raise FetchError(
                    "Not found (404): filing/CUSIP not found or not yet processed "
                    f"on 13f.info — {url}"
                )
            if resp.status_code >= 500:
                last_exc = FetchError(f"Server error {resp.status_code} from {url}")
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise last_exc
            resp.raise_for_status()
            body = resp.json()
            _write_cache(url, body)
            return body
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP error {exc.response.status_code} from {url}") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"Network error fetching {url}: {exc}") from exc
    raise FetchError(f"Failed to fetch {url}: {last_exc}")
