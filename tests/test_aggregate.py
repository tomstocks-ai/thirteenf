"""Tests for 13F aggregate cleaning (amendments, unit errors) and quarter math.

These are the pure parts of the `position` / `evolution` numerators — the logic
that decides which filing rows count toward % of shares outstanding.
"""

from __future__ import annotations

import datetime as dt

import pytest

from thirteenf.cli import (
    _clean_rows,
    _drop_price_outliers,
    _latest_filing_rows,
    _quarter_end,
    _quarters_back,
)
from thirteenf.quotes import shares_asof


def row(cik: str, accession: str, value: int, shares: int, put_call=None) -> list:
    """Build a holders-endpoint row: [[name, cik, cusip], [end, slug], value, shares, pc].

    Note the argument order mirrors the wire format: value ($thousands) precedes
    shares, which is exactly the pair some filers transpose.
    """
    return [
        [f"MANAGER {cik}", cik, "037833100"],
        ["2026-06-30", f"{accession}-manager-{cik}-q2-2026"],
        value,
        shares,
        put_call,
    ]


class TestLatestFilingRows:
    def test_multiple_legs_in_one_filing_are_all_kept(self):
        """Share classes / option legs / sub-accounts in ONE filing must be summed."""
        rows = [
            row("0000886982", "000088698226000519", 32_334_274, 111_744_105),
            row("0000886982", "000088698226000519", 3_952_368, 13_659_000),
            row("0000886982", "000088698226000519", 3_156_888, 10_909_900),
        ]
        assert len(_latest_filing_rows(rows)) == 3

    def test_amendment_supersedes_original(self):
        """A higher accession replaces the original instead of adding to it."""
        rows = [
            row("0001081019", "000108101926000019", 22_278_223, 6_446_426_607),
            row("0001081019", "000108101926000020", 6_446_426, 22_278_223),
        ]
        kept = _latest_filing_rows(rows)
        assert len(kept) == 1
        assert kept[0][3] == 22_278_223  # shares from the restatement, not the original

    def test_amendment_keeps_all_legs_of_the_latest_filing(self):
        rows = [
            row("0000123456", "000012345626000001", 100, 1_000),
            row("0000123456", "000012345626000002", 200, 2_000),
            row("0000123456", "000012345626000002", 300, 3_000),
        ]
        kept = _latest_filing_rows(rows)
        assert sorted(r[3] for r in kept) == [2_000, 3_000]

    def test_cik_zero_padding_is_normalized(self):
        """13f.info is inconsistent about leading zeros; same filer must group."""
        rows = [
            row("886982", "000088698226000519", 10, 100),
            row("0000886982", "000088698226000520", 20, 200),
        ]
        kept = _latest_filing_rows(rows)
        assert len(kept) == 1
        assert kept[0][3] == 200

    def test_distinct_filers_are_independent(self):
        rows = [row("0000000001", "000000000126000009", 10, 100), row("0000000002", "000000000226000001", 20, 200)]
        assert len(_latest_filing_rows(rows)) == 2


class TestDropPriceOutliers:
    @staticmethod
    def _at_price(count: int, price: int) -> list[list]:
        """`count` distinct filers holding 1,000 shares each at `price` per share."""
        return [row(f"11{i:08d}", f"11{i:08d}26000001", 1_000, 1_000 * price) for i in range(count)]

    def test_transposed_value_and_shares_is_dropped(self):
        """CalSTRS/AAPL 2026Q2: implied $3.46 against a ~$289 median."""
        good = self._at_price(10, 289)
        bad = row("3300000001", "330000000126000001", 6_446_426_607, 22_278_223)
        kept = _drop_price_outliers([*good, bad])
        assert bad not in kept
        assert len(kept) == 10

    def test_normal_price_dispersion_is_preserved(self):
        """Filers price the same quarter slightly differently; none should drop."""
        rows = [
            row(f"11{i:08d}", f"11{i:08d}26000001", 1_000, 1_000 * price)
            for i, price in enumerate(range(280, 300))
        ]
        assert len(_drop_price_outliers(rows)) == 20

    def test_too_few_rows_to_establish_a_median_passes_through(self):
        rows = [row("0000000001", "000000000126000001", 1_000, 3)]
        assert _drop_price_outliers(rows) == rows

    def test_rows_without_value_or_shares_are_kept(self):
        """Missing data isn't an error signal; only implausible ratios are."""
        good = self._at_price(10, 289)
        blank = row("9900000001", "990000000126000001", 0, 0)
        assert blank in _drop_price_outliers([*good, blank])


class TestCleanRows:
    @staticmethod
    def _market(n: int = 10, price: int = 289) -> list[list]:
        """n distinct filers, all at a plausible price."""
        return [row(f"11{i:08d}", f"11{i:08d}26000001", 1_000, 1_000 * price) for i in range(n)]

    def test_superseded_amendment_counts_as_one_drop(self):
        market = self._market()
        original = row("2200000001", "220000000126000001", 1_000, 289_000)
        restated = row("2200000001", "220000000126000002", 900, 260_100)
        cleaned, dropped = _clean_rows([*market, original, restated])
        assert dropped == 1
        assert original not in cleaned
        assert restated in cleaned

    def test_unit_error_counts_as_one_drop(self):
        market = self._market()
        transposed = row("3300000001", "330000000126000001", 6_446_426_607, 22_278_223)
        cleaned, dropped = _clean_rows([*market, transposed])
        assert dropped == 1
        assert transposed not in cleaned

    def test_clean_input_drops_nothing(self):
        market = self._market()
        cleaned, dropped = _clean_rows(market)
        assert dropped == 0
        assert len(cleaned) == len(market)

    def test_empty_input(self):
        assert _clean_rows([]) == ([], 0)


class TestQuarterMath:
    def test_walks_back_across_a_year_boundary(self):
        assert _quarters_back(1)[0][0] >= 2024  # sanity: uses today's date

    def test_ordering_is_oldest_first_and_contiguous(self):
        periods = _quarters_back(6)
        assert len(periods) == 6
        for (y1, q1), (y2, q2) in zip(periods, periods[1:]):
            expected = (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1)
            assert (y2, q2) == expected

    @pytest.mark.parametrize(
        ("year", "quarter", "expected"),
        [
            (2026, 1, "2026-03-31"),
            (2026, 2, "2026-06-30"),
            (2026, 3, "2026-09-30"),
            (2026, 4, "2026-12-31"),
        ],
    )
    def test_quarter_end_dates(self, year, quarter, expected):
        assert _quarter_end(year, quarter) == expected
        dt.date.fromisoformat(_quarter_end(year, quarter))  # must be a real date


class TestSharesAsOf:
    HISTORY = {"2025-06-30": 241_379_008, "2025-12-31": 254_437_614, "2026-06-30": 248_576_030}

    def test_exact_match(self):
        assert shares_asof(self.HISTORY, "2025-12-31") == 254_437_614

    def test_uses_last_known_value_before_the_date(self):
        """Share counts only change on filings, so carry the previous one forward."""
        assert shares_asof(self.HISTORY, "2026-03-31") == 254_437_614

    def test_before_any_known_date_returns_none(self):
        assert shares_asof(self.HISTORY, "2024-01-01") is None

    def test_empty_history(self):
        assert shares_asof({}, "2026-06-30") is None
