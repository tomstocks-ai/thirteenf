"""Shared quarter-over-quarter position-change model.

Wraps 13f.info's compare row — the per-position diff between two filings:
    [symbol, issuer, class_title, cusip, put_call,
     shares_before, shares_after, shares_delta, shares_delta_pct,
     value_before, value_after, value_delta, value_delta_pct]
    (values in $thousands)

Classification is SHARE-based, matching `position`: a fund that sells shares
into a rising price is REDUCED, not "increased" — value-only classification
mislabels price drift as conviction. `compare` and `consensus` both consume
Change objects so the semantics stay identical everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# status vocabulary (lowercase, matches --only choices)
STATUSES = ("new", "increased", "reduced", "closed", "unchanged")


@dataclass
class Change:
    """One position's change between two 13F filings."""

    symbol: Optional[str]
    issuer: str
    class_title: Optional[str]
    cusip: str
    put_call: Optional[str]
    shares_before: int
    shares_after: int
    shares_delta: int
    shares_delta_pct: Optional[float]
    value_before: int  # $thousands
    value_after: int  # $thousands
    value_delta: int  # $thousands
    value_delta_pct: Optional[float]

    @classmethod
    def from_row(cls, r: list) -> "Change":
        """Parse a raw 13f.info compare row (tolerates None numerics)."""
        return cls(
            symbol=r[0],
            issuer=r[1] or "",
            class_title=r[2],
            cusip=r[3],
            put_call=r[4],
            shares_before=r[5] or 0,
            shares_after=r[6] or 0,
            shares_delta=r[7] or 0,
            shares_delta_pct=r[8],
            value_before=r[9] or 0,
            value_after=r[10] or 0,
            value_delta=r[11] or 0,
            value_delta_pct=r[12],
        )

    @property
    def status(self) -> str:
        """new / increased / reduced / closed / unchanged — by SHARES."""
        if self.shares_before == 0 and self.shares_after > 0:
            return "new"
        if self.shares_after == 0 and self.shares_before > 0:
            return "closed"
        if self.shares_after > self.shares_before:
            return "increased"
        if self.shares_after < self.shares_before:
            return "reduced"
        return "unchanged"

    @property
    def holds_after(self) -> bool:
        return self.value_after > 0

    def to_dict(self) -> dict:
        """Named-field JSON dict (agent-friendly)."""
        return {
            "symbol": self.symbol,
            "issuer": self.issuer,
            "class": self.class_title,
            "cusip": self.cusip,
            "put_call": self.put_call,
            "shares_before": self.shares_before,
            "shares_after": self.shares_after,
            "shares_delta": self.shares_delta,
            "shares_delta_pct": self.shares_delta_pct,
            "value_before_thousands": self.value_before,
            "value_after_thousands": self.value_after,
            "value_delta_thousands": self.value_delta,
            "value_delta_pct": self.value_delta_pct,
            "status": self.status,
        }
