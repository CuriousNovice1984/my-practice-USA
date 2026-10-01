"""
Tests for the US calendar/tax helpers in utils/practice_days.py.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from my_practice.models import Practice
from my_practice.utils.practice_days import (
    HOME_OFFICE_MAX_SQFT,
    HomeOfficeCalculator,
    estimated_tax_periods,
    self_employment_tax_estimate,
    us_federal_holiday_names,
    us_federal_holidays,
)


class USFederalHolidaysTestCase(TestCase):
    """Observed federal holiday dates (OPM schedule)."""

    def test_2026_dates(self):
        self.assertEqual(
            us_federal_holidays(2026),
            {
                date(2026, 1, 1),  # New Year's Day
                date(2026, 1, 19),  # MLK Day
                date(2026, 2, 16),  # Washington's Birthday
                date(2026, 5, 25),  # Memorial Day
                date(2026, 6, 19),  # Juneteenth
                date(2026, 7, 3),  # Independence Day (Jul 4 is a Saturday)
                date(2026, 9, 7),  # Labor Day
                date(2026, 10, 12),  # Columbus Day
                date(2026, 11, 11),  # Veterans Day
                date(2026, 11, 26),  # Thanksgiving
                date(2026, 12, 25),  # Christmas
            },
        )

    def test_sunday_holiday_observed_monday(self):
        # Christmas 2022 fell on a Sunday
        self.assertIn(date(2022, 12, 26), us_federal_holidays(2022))
        self.assertNotIn(date(2022, 12, 25), us_federal_holidays(2022))

    def test_saturday_new_year_observed_in_prior_year(self):
        # 1 Jan 2022 was a Saturday — observed Friday 31 Dec 2021
        self.assertIn(date(2021, 12, 31), us_federal_holidays(2021))

    def test_juneteenth_not_before_2021(self):
        self.assertNotIn("Juneteenth", us_federal_holiday_names(2020).values())
        self.assertIn("Juneteenth", us_federal_holiday_names(2021).values())


class EstimatedTaxPeriodsTestCase(TestCase):
    """IRS Form 1040-ES periods and due dates."""

    def test_periods_are_not_calendar_quarters(self):
        periods = estimated_tax_periods(2026)
        self.assertEqual(
            [(p.start, p.end) for p in periods],
            [
                (date(2026, 1, 1), date(2026, 3, 31)),
                (date(2026, 4, 1), date(2026, 5, 31)),
                (date(2026, 6, 1), date(2026, 8, 31)),
                (date(2026, 9, 1), date(2026, 12, 31)),
            ],
        )

    def test_due_dates_2026(self):
        self.assertEqual(
            [p.due for p in estimated_tax_periods(2026)],
            [date(2026, 4, 15), date(2026, 6, 15), date(2026, 9, 15), date(2027, 1, 15)],
        )

    def test_weekend_due_date_rolls_forward(self):
        # 15 Jun 2025 was a Sunday
        self.assertEqual(estimated_tax_periods(2025)[1].due, date(2025, 6, 16))

    def test_labels(self):
        self.assertEqual([p.label for p in estimated_tax_periods(2026)], ["Q1", "Q2", "Q3", "Q4"])


class SelfEmploymentTaxTestCase(TestCase):
    def test_estimate(self):
        # 10,000 × 0.9235 × 0.153 = 1,412.955 → 1,412.96
        self.assertEqual(self_employment_tax_estimate(Decimal("10000")), Decimal("1412.96"))

    def test_loss_is_zero(self):
        self.assertEqual(self_employment_tax_estimate(Decimal("-500")), Decimal("0.00"))


class HomeOfficeCalculatorTestCase(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Test Practice", slug="test-ho")

    def test_not_configured(self):
        result = HomeOfficeCalculator(self.practice, 2026).calculate()
        self.assertFalse(result.is_configured)
        self.assertEqual(result.deduction_total, Decimal("0"))

    def test_rate_per_square_foot(self):
        self.practice.home_office_sqft = 150
        result = HomeOfficeCalculator(self.practice, 2026).calculate()
        self.assertTrue(result.is_configured)
        self.assertEqual(result.deduction_total, Decimal("750"))

    def test_capped_at_300_sqft(self):
        self.practice.home_office_sqft = 450
        result = HomeOfficeCalculator(self.practice, 2026).calculate()
        self.assertEqual(result.counted_square_feet, HOME_OFFICE_MAX_SQFT)
        self.assertEqual(result.deduction_total, Decimal("1500"))
