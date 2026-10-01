"""
US calendar and tax-year helpers for a self-employed practice.

- ``us_federal_holidays`` — the eleven federal holidays (observed dates), used
  to exclude closures from working-day and capacity calculations. Other
  closures (e.g. the day after Thanksgiving) are recorded as TimeOff.
- ``estimated_tax_periods`` — the IRS Form 1040-ES payment periods and their
  due dates. They are *not* calendar quarters: Q2 covers only April–May and Q3
  June–August.
- ``self_employment_tax_estimate`` — Schedule SE estimate on net profit.
- ``HomeOfficeCalculator`` — the IRS simplified home office deduction
  ($5 per square foot, up to 300 sq ft).

These are planning estimates, not tax advice — the tax pages say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Practice


# IRS simplified method for business use of home (Rev. Proc. 2013-13)
HOME_OFFICE_RATE_PER_SQFT = Decimal("5")
HOME_OFFICE_MAX_SQFT = 300

# Schedule SE: 92.35% of net earnings is subject to the 15.3% SE tax
# (12.4% Social Security up to the annual wage base + 2.9% Medicare)
SE_TAX_EARNINGS_FACTOR = Decimal("0.9235")
SE_TAX_RATE = Decimal("0.153")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th ``weekday`` (0=Mon) of a month; ``n=-1`` for the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    next_month = date(year + month // 12, month % 12 + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """Federal observance rule: Saturday → preceding Friday, Sunday → following Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def us_federal_holiday_names(year: int) -> dict[date, str]:
    """Return {observed date: name} for the US federal holidays of ``year``."""
    holidays = {
        _observed(date(year, 1, 1)): "New Year's Day",
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        _nth_weekday(year, 5, 0, -1): "Memorial Day",
        _observed(date(year, 7, 4)): "Independence Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 10, 0, 2): "Columbus Day",
        _observed(date(year, 11, 11)): "Veterans Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
        _observed(date(year, 12, 25)): "Christmas Day",
    }
    # Juneteenth became a federal holiday in 2021
    if year >= 2021:
        holidays[_observed(date(year, 6, 19))] = "Juneteenth"
    # When next New Year's Day is a Saturday it is observed on 31 Dec of this year
    next_new_year = _observed(date(year + 1, 1, 1))
    if next_new_year.year == year:
        holidays[next_new_year] = "New Year's Day"
    return holidays


def us_federal_holidays(year: int) -> set[date]:
    """Return the set of observed US federal holiday dates for ``year``."""
    return set(us_federal_holiday_names(year))


def _next_business_day(day: date) -> date:
    """Roll a due date that falls on a weekend or federal holiday forward."""
    while day.weekday() >= 5 or day in us_federal_holidays(day.year):
        day += timedelta(days=1)
    return day


@dataclass(frozen=True)
class EstimatedTaxPeriod:
    """One IRS estimated-tax payment period (Form 1040-ES)."""

    number: int
    start: date
    end: date
    due: date

    @property
    def label(self) -> str:
        return f"Q{self.number}"


def estimated_tax_periods(year: int) -> list[EstimatedTaxPeriod]:
    """The four 1040-ES periods for ``year`` with their (business-day adjusted) due dates."""
    raw = [
        (1, date(year, 1, 1), date(year, 3, 31), date(year, 4, 15)),
        (2, date(year, 4, 1), date(year, 5, 31), date(year, 6, 15)),
        (3, date(year, 6, 1), date(year, 8, 31), date(year, 9, 15)),
        (4, date(year, 9, 1), date(year, 12, 31), date(year + 1, 1, 15)),
    ]
    return [
        EstimatedTaxPeriod(number=n, start=s, end=e, due=_next_business_day(d))
        for n, s, e, d in raw
    ]


def self_employment_tax_estimate(net_profit: Decimal) -> Decimal:
    """Estimated self-employment tax on ``net_profit`` (zero for a loss).

    Ignores the Social Security wage-base cap, so it overstates the tax only
    for net earnings above the cap.
    """
    if net_profit <= 0:
        return Decimal("0.00")
    return (net_profit * SE_TAX_EARNINGS_FACTOR * SE_TAX_RATE).quantize(Decimal("0.01"))


@dataclass
class HomeOfficeResult:
    """Result of the simplified home office deduction."""

    year: int
    square_feet: int
    counted_square_feet: int  # capped at HOME_OFFICE_MAX_SQFT
    deduction_total: Decimal

    @property
    def is_configured(self) -> bool:
        return self.square_feet > 0


class HomeOfficeCalculator:
    """IRS simplified home office deduction: $5 × office square feet (max 300).

    The deduction can't exceed the business's gross income minus other
    expenses; the tax summary applies that limit where it knows net profit.
    """

    def __init__(self, practice: Practice, year: int) -> None:
        self.practice = practice
        self.year = year

    def calculate(self) -> HomeOfficeResult:
        square_feet = self.practice.home_office_sqft or 0
        counted = min(square_feet, HOME_OFFICE_MAX_SQFT)
        return HomeOfficeResult(
            year=self.year,
            square_feet=square_feet,
            counted_square_feet=counted,
            deduction_total=Decimal(counted) * HOME_OFFICE_RATE_PER_SQFT,
        )
