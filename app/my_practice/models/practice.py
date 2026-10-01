"""Practice/practitioner configuration model"""

from typing import Any

from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from ..us_states import US_STATE_CHOICES
from ..validators import validate_email_template_placeholders


class Practice(models.Model):
    """
    Practice information for invoices and contact details.

    Supports multi-practice setups where one user can manage multiple
    separate businesses (e.g., Therapy Practice + Coaching Business).
    """

    # Users with access to this practice (via UserPractice M2M)
    users: models.ManyToManyField = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="UserPractice",
        related_name="practices",
        verbose_name=_("Users"),
    )

    name = models.CharField(max_length=200, default="", verbose_name=_("Practitioner name"))
    slug = models.SlugField(
        max_length=50,
        unique=True,
        default="default",
        verbose_name=_("URL slug"),
        help_text=_("Unique identifier for the practice (e.g. 'therapy', 'coaching')"),
    )
    short_title = models.CharField(
        max_length=50,
        default="Therapy",
        verbose_name=_("Short title"),
        help_text=_("Short label for the title bar (e.g. 'Therapy')"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_("Inactive practices are not shown"),
    )
    title = models.CharField(
        max_length=200,
        default="Licensed Professional Counselor (LPC)",
        verbose_name=_("Professional title"),
    )
    subtitle = models.CharField(
        max_length=200,
        default="",
        verbose_name=_("Subtitle"),
        blank=True,
    )

    # Address
    street = models.CharField(max_length=200, default="", verbose_name=_("Street address"))
    city = models.CharField(max_length=100, default="", verbose_name=_("City"))
    state = models.CharField(
        max_length=2, choices=US_STATE_CHOICES, default="TX", verbose_name=_("State")
    )
    postal_code = models.CharField(max_length=20, default="", verbose_name=_("ZIP code"))
    country = models.CharField(
        max_length=100, default="United States", blank=True, verbose_name=_("Country")
    )

    # Contact
    email = models.EmailField(default="", verbose_name=_("Email"))
    email_from_name = models.CharField(
        max_length=200,
        default="",
        verbose_name=_("Email sender name"),
        help_text=_("Name displayed in 'From' field of outgoing emails"),
    )
    website = models.URLField(default="", verbose_name=_("Website"))
    booking_url = models.URLField(
        default="",
        blank=True,
        verbose_name=_("Booking URL"),
        help_text=_(
            "Link to online appointment booking (e.g. Calendly). "
            "Automatically inserted into inquiry email templates."
        ),
    )
    phone = models.CharField(max_length=50, blank=True, verbose_name=_("Phone"))

    # How clients pay — printed on invoices and payment reminders
    payment_instructions = models.TextField(
        default="",
        blank=True,
        verbose_name=_("Payment instructions"),
        help_text=_(
            "How clients can pay, printed on invoices and payment reminders "
            "(e.g. 'Zelle: payments@practice.example · Checks payable to Practice LLC')"
        ),
    )
    private_bank_account = models.CharField(
        max_length=34,
        blank=True,
        verbose_name=_("Private bank account"),
        help_text=_(
            "Identifier of your personal account as it appears in bank exports "
            "(e.g. the last four digits), for automatic detection of owner draws "
            "and contributions during bank import"
        ),
    )

    # Bank statement CSV import format. Defaults fit the common US export shape
    # (Date, Description, Amount); adjust per bank without touching code. Optional
    # columns left blank are simply not read.
    csv_delimiter = models.CharField(
        max_length=1,
        default=",",
        verbose_name=_("CSV delimiter"),
        help_text=_("Column separator used by your bank's CSV export, e.g. ',' or ';'"),
    )
    csv_column_date = models.CharField(
        max_length=100,
        default="Date",
        verbose_name=_("CSV column: date"),
        help_text=_("Header name of the transaction date column in your bank's CSV export"),
    )
    csv_column_value_date = models.CharField(
        max_length=100,
        default="",
        blank=True,
        verbose_name=_("CSV column: posted date"),
        help_text=_("Optional: header name of the posted/settled date column"),
    )
    csv_column_payer_name = models.CharField(
        max_length=100,
        default="Description",
        verbose_name=_("CSV column: payer/payee name"),
        help_text=_("Header name of the payer/payee (or description) column"),
    )
    csv_column_payer_account = models.CharField(
        max_length=100,
        default="",
        blank=True,
        verbose_name=_("CSV column: payer/payee account"),
        help_text=_("Optional: header name of a counterparty account column"),
    )
    csv_column_reference = models.CharField(
        max_length=100,
        default="Description",
        verbose_name=_("CSV column: memo"),
        help_text=_("Header name of the memo/description column searched for invoice numbers"),
    )
    csv_column_amount = models.CharField(
        max_length=100,
        default="Amount",
        verbose_name=_("CSV column: amount"),
        help_text=_("Header name of the transaction amount column (negative = money out)"),
    )
    csv_column_balance = models.CharField(
        max_length=100,
        default="",
        blank=True,
        verbose_name=_("CSV column: balance after transaction"),
        help_text=_("Optional: header name of the running balance column"),
    )
    csv_column_account = models.CharField(
        max_length=100,
        default="",
        blank=True,
        verbose_name=_("CSV column: account"),
        help_text=_("Optional: header name of the source account column"),
    )

    # Invoice follow-up
    overdue_after_days = models.PositiveIntegerField(
        default=30,
        verbose_name=_("Overdue after (days)"),
        help_text=_(
            "Days after the invoice date before a sent invoice is flagged as "
            "overdue (dashboard widget, Focus Queue)."
        ),
    )

    # Tax
    tax_id = models.CharField(
        max_length=50,
        default="",
        blank=True,
        verbose_name=_("Tax ID (EIN)"),
        help_text=_("Employer Identification Number, printed on invoices"),
    )

    # Records retention — when an inactive client's records may be destroyed
    records_retention_years = models.PositiveSmallIntegerField(
        default=7,
        verbose_name=_("Records retention (years)"),
        help_text=_(
            "Years to keep records after the last session. For minors the period "
            "runs from their 18th birthday instead, whichever ends later. Use the "
            "longest period required by any state you are licensed in."
        ),
    )

    # Free-form (non-session) invoice items — day-rate/project billing (P-122)
    allows_free_form_items = models.BooleanField(
        default=False,
        verbose_name=_("Allow free-form invoice items"),
        help_text=_(
            "Lets invoice items skip the linked session and use a free-text "
            "description instead — for day-rate or project billing that isn't "
            "tied to a therapy/coaching session. Leave off for therapy/coaching "
            "practices, where every invoice item must stay linked to a session."
        ),
    )

    # Professional memberships, printed in the invoice footer
    professional_memberships = models.TextField(
        default="",
        verbose_name=_("Memberships"),
        blank=True,
    )

    # Images
    logo = models.ImageField(upload_to="practice/", blank=True, null=True, verbose_name=_("Logo"))
    signature = models.ImageField(
        upload_to="practice/", blank=True, null=True, verbose_name=_("Signature")
    )

    # Payment terms
    payment_terms_days = models.IntegerField(default=14, verbose_name=_("Payment term (days)"))
    payment_terms_text = models.CharField(
        max_length=200,
        default="Payment is due within 14 days of the invoice date. Please include the invoice number with your payment.",
        verbose_name=_("Payment terms"),
    )

    # Email templates for invoices
    invoice_email_subject = models.CharField(
        validators=[validate_email_template_placeholders],
        max_length=200,
        default="Invoice {invoice_number}",
        verbose_name=_("Email subject"),
        help_text=_("Placeholders: {invoice_number}, {amount}, {date}, {client_name}"),
    )
    invoice_email_body = models.TextField(
        validators=[validate_email_template_placeholders],
        default="{salutation},\n\n{sessions_intro}Please find attached invoice {invoice_number} for {amount} dated {date}.\n\n"
        "Payment is due within 14 days.\n\n"
        "The invoice is attached as a PDF.",
        verbose_name=_("Email body"),
        help_text=_(
            "Placeholders: {salutation}, {sessions_intro}, {invoice_number}, {amount}, {date}, {client_name}"
        ),
    )
    email_signature = models.TextField(
        default="Best regards,\nLicensed Professional Counselor (LPC)",
        verbose_name=_("Email signature"),
        help_text=_("Used for all outgoing emails"),
    )

    # Home office (IRS simplified method)
    home_office_sqft = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Home office area (sq ft)"),
        help_text=_(
            "Square footage used regularly and exclusively for the practice, for the "
            "simplified home office deduction ($5/sq ft, up to 300 sq ft). Leave empty "
            "if you don't claim one."
        ),
    )

    # Capacity Monitoring (P-013 Phase 3)
    monthly_target_hours = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name=_("Monthly target: hours"),
        help_text=_(
            "Target hours (sessions) per month, e.g. 60.0. Enables capacity "
            "monitoring on the dashboard."
        ),
    )
    monthly_target_revenue = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Monthly target: revenue ($)"),
        help_text=_(
            "Target revenue per month in $, e.g. 3000.00. Enables capacity "
            "monitoring on the dashboard."
        ),
    )

    class Meta:
        verbose_name = _("Practice settings")
        verbose_name_plural = _("Practice settings")

    def __str__(self) -> str:
        return f"{self.name} - {self.title}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Auto-generate slug from name if not set or still default"""
        if not self.slug or self.slug == "default":
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CapacityPeriod(models.Model):
    """
    Defines available therapy hours per week for a given practice, from a start date onward.

    Periods are ordered by start_date. Each period is in effect from its start_date
    until the next period's start_date (or indefinitely if it is the last one).
    """

    practice = models.ForeignKey(
        Practice,
        on_delete=models.CASCADE,
        related_name="capacity_periods",
        verbose_name=_("Practice"),
    )
    start_date = models.DateField(verbose_name=_("Valid from"))
    hours_per_week = models.PositiveSmallIntegerField(
        verbose_name=_("Hours/week"),
        help_text=_("Available therapy hours per week from this date"),
    )

    class Meta:
        verbose_name = _("Capacity period")
        verbose_name_plural = _("Capacity periods")
        ordering = ["start_date"]
        unique_together = [["practice", "start_date"]]

    def __str__(self) -> str:
        return f"{self.start_date}: {self.hours_per_week}h/{_('week')}"


class UserPractice(models.Model):
    """
    Many-to-Many through table linking users to practices.

    Allows one user to manage multiple practices and tracks
    ownership/access rights per practice.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="practice_memberships",
        verbose_name=_("User"),
    )
    practice = models.ForeignKey(
        Practice,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Practice"),
    )
    is_owner = models.BooleanField(
        default=False,
        verbose_name=_("Owner"),
        help_text=_("Owners have full administrative rights"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created on"))

    class Meta:
        verbose_name = _("User-practice assignment")
        verbose_name_plural = _("User-practice assignments")
        unique_together = [["user", "practice"]]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        owner_str = f" ({_('Owner')})" if self.is_owner else ""
        return f"{self.user.username} → {self.practice.name}{owner_str}"
