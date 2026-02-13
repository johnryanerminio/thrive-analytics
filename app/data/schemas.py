"""
Period filter schemas for time-based queries.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PeriodType(str, Enum):
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    CUSTOM = "custom"
    RANGE = "range"
    ALL = "all"


@dataclass
class PeriodFilter:
    """Defines a date range for filtering sales data."""
    period_type: PeriodType = PeriodType.ALL
    year: Optional[int] = None
    month: Optional[int] = None          # 1-12
    quarter: Optional[int] = None        # 1-4
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    store: Optional[str] = None          # optional store filter
    # Range fields (for multi-month picker)
    start_year: Optional[int] = None
    start_month: Optional[int] = None    # 1-12
    end_year: Optional[int] = None
    end_month: Optional[int] = None      # 1-12

    def resolve(self) -> tuple[Optional[dt.date], Optional[dt.date]]:
        """Return (start_date, end_date) based on period_type."""
        if self.period_type == PeriodType.ALL:
            return None, None

        if self.period_type == PeriodType.RANGE:
            if self.start_year and self.start_month and self.end_year and self.end_month:
                s = dt.date(self.start_year, self.start_month, 1)
                if self.end_month == 12:
                    e = dt.date(self.end_year + 1, 1, 1) - dt.timedelta(days=1)
                else:
                    e = dt.date(self.end_year, self.end_month + 1, 1) - dt.timedelta(days=1)
                return s, e
            return None, None

        if self.period_type == PeriodType.CUSTOM:
            return self.start_date, self.end_date

        if self.year is None:
            return None, None

        if self.period_type == PeriodType.MONTH:
            if self.month is None:
                return None, None
            start = dt.date(self.year, self.month, 1)
            if self.month == 12:
                end = dt.date(self.year + 1, 1, 1) - dt.timedelta(days=1)
            else:
                end = dt.date(self.year, self.month + 1, 1) - dt.timedelta(days=1)
            return start, end

        if self.period_type == PeriodType.QUARTER:
            if self.quarter is None:
                return None, None
            start_month = (self.quarter - 1) * 3 + 1
            end_month = start_month + 2
            start = dt.date(self.year, start_month, 1)
            if end_month == 12:
                end = dt.date(self.year + 1, 1, 1) - dt.timedelta(days=1)
            else:
                end = dt.date(self.year, end_month + 1, 1) - dt.timedelta(days=1)
            return start, end

        if self.period_type == PeriodType.YEAR:
            return dt.date(self.year, 1, 1), dt.date(self.year, 12, 31)

        return None, None

    @property
    def label(self) -> str:
        """Human-readable label for the period."""
        if self.period_type == PeriodType.ALL:
            return "All Time"
        if self.period_type == PeriodType.MONTH and self.year and self.month:
            return f"{dt.date(self.year, self.month, 1):%B %Y}"
        if self.period_type == PeriodType.QUARTER and self.year and self.quarter:
            return f"Q{self.quarter} {self.year}"
        if self.period_type == PeriodType.YEAR and self.year:
            return str(self.year)
        if self.period_type == PeriodType.RANGE:
            if self.start_year and self.start_month and self.end_year and self.end_month:
                s = dt.date(self.start_year, self.start_month, 1)
                e = dt.date(self.end_year, self.end_month, 1)
                return f"{s:%b %Y} to {e:%b %Y}"
            return "Range"
        if self.period_type == PeriodType.CUSTOM:
            s = self.start_date.isoformat() if self.start_date else "?"
            e = self.end_date.isoformat() if self.end_date else "?"
            return f"{s} to {e}"
        return "Unknown"

    def previous(self) -> "PeriodFilter":
        """Return the immediately preceding period of the same type."""
        if self.period_type == PeriodType.MONTH and self.year and self.month:
            if self.month == 1:
                return PeriodFilter(PeriodType.MONTH, self.year - 1, 12)
            return PeriodFilter(PeriodType.MONTH, self.year, self.month - 1)

        if self.period_type == PeriodType.QUARTER and self.year and self.quarter:
            if self.quarter == 1:
                return PeriodFilter(PeriodType.QUARTER, self.year - 1, quarter=4)
            return PeriodFilter(PeriodType.QUARTER, self.year, quarter=self.quarter - 1)

        if self.period_type == PeriodType.YEAR and self.year:
            return PeriodFilter(PeriodType.YEAR, self.year - 1)

        if self.period_type == PeriodType.CUSTOM and self.start_date and self.end_date:
            duration = self.end_date - self.start_date
            new_end = self.start_date - dt.timedelta(days=1)
            new_start = new_end - duration
            return PeriodFilter(
                PeriodType.CUSTOM,
                start_date=new_start,
                end_date=new_end,
            )

        return PeriodFilter(PeriodType.ALL)
