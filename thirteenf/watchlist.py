"""Built-in institution watchlist.

All CIKs verified live against the 13f.info autocomplete endpoint and/or the
SEC EDGAR submissions API (data.sec.gov) at build time.
"""

from __future__ import annotations

from typing import TypedDict


class Institution(TypedDict):
    name: str
    cik: str
    category: str  # "biotech" | "megafund"


WATCHLIST: list[Institution] = [
    # --- biotech ---
    {"name": "RA Capital Management", "cik": "0001346824", "category": "biotech"},
    {"name": "Perceptive Advisors", "cik": "0001224962", "category": "biotech"},
    {"name": "Deerfield Management", "cik": "0001009258", "category": "biotech"},
    {"name": "Baker Bros Advisors", "cik": "0001263508", "category": "biotech"},
    {"name": "Orbimed Advisors", "cik": "0001055951", "category": "biotech"},
    {"name": "Redmile Group", "cik": "0001425738", "category": "biotech"},
    {"name": "Cormorant Asset Management", "cik": "0001583977", "category": "biotech"},
    {"name": "Avoro Capital", "cik": "0001633313", "category": "biotech"},
    {"name": "Frazier Life Sciences", "cik": "0001892134", "category": "biotech"},
    {"name": "EcoR1 Capital", "cik": "0001587114", "category": "biotech"},
    {"name": "Casdin Capital", "cik": "0001534261", "category": "biotech"},
    {"name": "Rock Springs Capital", "cik": "0001595725", "category": "biotech"},
    {"name": "Boxer Capital", "cik": "0001465837", "category": "biotech"},
    # --- megafund ---
    {"name": "Citadel Advisors", "cik": "0001423053", "category": "megafund"},
    {"name": "Morgan Stanley", "cik": "0000895421", "category": "megafund"},
    {"name": "ARK Investment Management", "cik": "0001697748", "category": "megafund"},
    {"name": "Berkshire Hathaway", "cik": "0001067983", "category": "megafund"},
    {"name": "JPMorgan Chase", "cik": "0000019617", "category": "megafund"},
    {"name": "BlackRock", "cik": "0001364742", "category": "megafund"},
    {"name": "Vanguard Group", "cik": "0000102909", "category": "megafund"},
    {"name": "State Street", "cik": "0000093751", "category": "megafund"},
]
