"""
Tax year summary view - provides comprehensive financial overview for tax purposes.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..forms import TaxYearNoteForm
from ..models import CompanyExpense, CompanyWithdrawal, TaxYearNote
from ..utils import RevenueCalculator, TaxYearContextBuilder
from ..utils.practice_days import (
    EstimatedTaxPeriod,
    estimated_tax_periods,
    self_employment_tax_estimate,
)
from ..utils.tax_context_builder import available_data_years
from ..utils.view_helpers import get_year_from_request


def tax_year_summary(request: HttpRequest) -> HttpResponse:
    """Generate comprehensive tax year summary with revenue, expenses, and deductions."""
    year = (
        get_year_from_request(request, "year", timezone.localdate().year)
        or timezone.localdate().year
    )
    context = TaxYearContextBuilder(year, request.current_practice, request.user).build(
        expense_sort=request.GET.get("sort", "date")
    )
    return render(request, "my_practice/tax_year_summary.html", context)


@require_POST
def save_tax_year_note(request: HttpRequest) -> JsonResponse:
    """
    Save (upsert) a TaxYearNote for the current practice and a given year.

    Accepts a POST body with:
      - year   (int)
      - note   (str, may be blank to clear)

    Returns JSON {saved: true, updated_at: "..."}.
    """
    practice = request.current_practice
    if not practice:
        return JsonResponse({"error": _("No practice selected")}, status=400)

    try:
        year = int(request.POST.get("year", 0))
    except TypeError, ValueError:
        return JsonResponse({"error": _("Invalid year")}, status=400)

    if not (1900 <= year <= 2100):
        return JsonResponse({"error": _("Invalid year")}, status=400)

    note_form = TaxYearNoteForm()

    defaults: dict = {}
    if "note" in request.POST:
        defaults["allocation_note"] = request.POST.get("note", "").strip()

    raw_amount = request.POST.get("settlement_amount", "").strip()
    if raw_amount != "":
        try:
            defaults["settlement_amount"] = note_form.fields["settlement_amount"].clean(
                raw_amount.replace(",", ".")
            )
        except ValidationError:
            return JsonResponse({"error": _("Invalid amount")}, status=400)
    elif "settlement_amount" in request.POST:
        defaults["settlement_amount"] = None

    raw_date = request.POST.get("settlement_date", "").strip()
    if raw_date != "":
        try:
            defaults["settlement_date"] = note_form.fields["settlement_date"].clean(raw_date)
        except ValidationError:
            return JsonResponse({"error": _("Invalid date")}, status=400)
    elif "settlement_date" in request.POST:
        defaults["settlement_date"] = None

    obj, _created = TaxYearNote.objects.update_or_create(
        practice=practice,
        year=year,
        defaults=defaults,
    )
    return JsonResponse({"saved": True, "updated_at": obj.updated_at.strftime("%d %b %y %H:%M")})


def _build_period_data(period: EstimatedTaxPeriod, previous_due: date, practice, today) -> dict:
    """Revenue/expenses/estimated-tax payments for one 1040-ES period."""
    start, end = period.start, period.end

    # Same paid-date rule (with invoice_date fallback) as the year summary,
    # so periods sum to the year total
    revenue = RevenueCalculator.get_paid_revenue_for_range(start, end, practice=practice)

    expenses = CompanyExpense.objects.filter(
        practice=practice,
        date__range=(start, end),
        is_tax_deductible=True,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # A payment counts toward the period whose due date it was made by: payments
    # after the previous due date up to and including this one.
    tax_withdrawals = CompanyWithdrawal.objects.filter(
        practice=practice,
        category="tax",
        date__gt=previous_due,
        date__lte=period.due,
    ).order_by("date")
    tax_paid = sum(w.amount for w in tax_withdrawals)

    net_profit = revenue - expenses
    is_complete = today > end
    is_current = start <= today <= end
    is_overdue = today > period.due
    # Flag periods with profit but no payment once the due date is near or past
    due_soon = timedelta(0) <= period.due - today <= timedelta(days=30)
    needs_attention = (is_overdue or due_soon) and net_profit > 0 and not tax_withdrawals.exists()

    return {
        "number": period.number,
        "label": period.label,
        "start": start,
        "end": end,
        "due": period.due,
        "revenue": revenue,
        "expenses": expenses,
        "net_profit": net_profit,
        "se_tax_estimate": self_employment_tax_estimate(net_profit),
        "tax_withdrawals": tax_withdrawals,
        "tax_paid": tax_paid,
        "is_complete": is_complete,
        "is_current": is_current,
        "needs_attention": needs_attention,
    }


def _tax_note_context(practice, year: int, total_tax_paid: Decimal) -> dict:
    """Settlement amount/date from TaxYearNote, plus the resulting net tax position."""
    tax_note = (
        TaxYearNote.objects.filter(practice=practice, year=year).first() if practice else None
    )
    settlement_amount = tax_note.settlement_amount if tax_note else None
    settlement_date = tax_note.settlement_date if tax_note else None
    net_tax_position = total_tax_paid + settlement_amount if settlement_amount is not None else None
    return {
        "settlement_amount": settlement_amount,
        "settlement_date": settlement_date,
        "net_tax_position": net_tax_position,
    }


def _add_tax_payment_url(year: int) -> str:
    """Quick-add URL for an estimated tax payment, returning to this year's overview.

    The withdrawal form honours ?next= (NextRedirectMixin), so saving or
    cancelling comes back here rather than dropping the user on the withdrawal
    list. The year rides along so it is the same view, not just the same page.
    """
    back = f"{reverse('tax_quarter_overview')}?{urlencode({'year': year})}"
    return f"{reverse('withdrawal_create')}?{urlencode({'category': 'tax', 'next': back})}"


def tax_quarter_overview(request: HttpRequest) -> HttpResponse:
    """
    Quarterly estimated tax overview (IRS Form 1040-ES, P-013 Phase 2).

    Shows per-period revenue, deductible expenses, net profit and an estimated
    self-employment tax for the selected year, with each period's due date, plus
    the estimated tax payments recorded as withdrawals (category='tax').
    Provides a quick-add link to record a new payment.
    """
    year = (
        get_year_from_request(request, "year", timezone.localdate().year)
        or timezone.localdate().year
    )
    practice = request.current_practice
    today = timezone.localdate()

    periods = estimated_tax_periods(year)
    # Q1 payments start the day after the prior year's Q4 due date (mid-January)
    previous_dues = [estimated_tax_periods(year - 1)[-1].due] + [p.due for p in periods[:-1]]
    quarters = [
        _build_period_data(period, previous_due, practice, today)
        for period, previous_due in zip(periods, previous_dues, strict=True)
    ]

    total_revenue: Decimal = sum((cast(Decimal, q["revenue"]) for q in quarters), Decimal("0"))
    total_expenses: Decimal = sum((cast(Decimal, q["expenses"]) for q in quarters), Decimal("0"))
    total_tax_paid: Decimal = sum((cast(Decimal, q["tax_paid"]) for q in quarters), Decimal("0"))
    total_net_profit = total_revenue - total_expenses

    available_years = available_data_years(practice, include_expenses=False) or [today.year]

    return render(
        request,
        "my_practice/tax_quarter_overview.html",
        {
            "quarters": quarters,
            "year": year,
            "available_years": available_years,
            "total_revenue": total_revenue,
            "total_expenses": total_expenses,
            "total_tax_paid": total_tax_paid,
            "total_net_profit": total_net_profit,
            "total_se_tax_estimate": self_employment_tax_estimate(total_net_profit),
            "add_payment_url": _add_tax_payment_url(year),
            "save_note_url": reverse("save_tax_year_note"),
            **_tax_note_context(practice, year, total_tax_paid),
        },
    )
