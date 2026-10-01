"""Financial tracking models for withdrawals and expenses"""

from enum import StrEnum
from pathlib import Path

from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .base import PracticeScopedManager, TimestampedModel


class CompanyWithdrawal(TimestampedModel):
    """Track money withdrawn from company account for personal use"""

    class Category(StrEnum):
        """Withdrawal category — determines cash-flow direction for accounting."""

        SALARY = "salary"
        TAX = "tax"
        PRIVATE_TRANSFER = "private_transfer"
        OTHER = "other"
        # Incoming / adjustments
        CONTRIBUTION = "contribution"
        CORRECTION = "correction"

    CATEGORY_CHOICES = [
        (Category.SALARY, _("Owner's draw")),
        (Category.TAX, _("Estimated tax payment")),
        (Category.PRIVATE_TRANSFER, _("Private transfer")),
        (Category.OTHER, _("Other")),
        # Incoming / adjustments
        (Category.CONTRIBUTION, _("Owner contribution")),
        (Category.CORRECTION, _("Incorrect posting / correction")),
    ]

    # Categories that represent money flowing *out* of the business account
    OUTGOING_CATEGORIES = {
        Category.SALARY,
        Category.TAX,
        Category.PRIVATE_TRANSFER,
        Category.OTHER,
    }
    # Categories that represent money flowing *in* or adjustments
    INCOMING_CATEGORIES = {Category.CONTRIBUTION, Category.CORRECTION}

    # Practice relationship
    practice = models.ForeignKey(
        "Practice",
        on_delete=models.PROTECT,
        related_name="withdrawals",
        verbose_name=_("Practice"),
    )

    date = models.DateField(verbose_name=_("Date"))
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount"),
        help_text=_("Negative amount for corrections/reversals"),
    )
    description = models.TextField(
        blank=True, verbose_name=_("Notes"), help_text=_("Optional: purpose")
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default=Category.SALARY,
        verbose_name=_("Category"),
    )

    # Practice-scoped manager
    objects = PracticeScopedManager()

    class Meta:
        ordering = ["-date"]
        verbose_name = _("Company Withdrawal")
        verbose_name_plural = _("Company Withdrawals")
        indexes = [
            models.Index(fields=["date"], name="withdrawal_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.date.strftime('%d %b %y')}: ${self.amount}"


class CompanyExpense(TimestampedModel):
    """Track company business expenses for tax and profit calculation"""

    class Category(StrEnum):
        """Expense category for tax reporting and profit calculation."""

        RENT = "rent"
        PHONE_INTERNET = "phone_internet"
        DUES = "dues"
        INSURANCE = "insurance"
        BANK_FEES = "bank_fees"
        LICENSES = "licenses"
        WEBSITE = "website"
        ADVERTISING = "advertising"
        SOFTWARE = "software"
        PERSONAL_THERAPY = "personal_therapy"
        SUPERVISION = "supervision"
        TRAINING = "training"
        TRAINING_TRAVEL = "training_travel"
        PEER_CONSULTATION = "peer_consultation"
        SUPPLIES = "supplies"
        HARDWARE = "hardware"
        BOOKS = "books"
        CONFERENCES = "conferences"
        OTHER = "other"

    # Schedule C line hints in the labels help when transferring the year's totals.
    CATEGORY_CHOICES = [
        (Category.RENT, _("Rent / office lease (Sch. C line 20b)")),
        (Category.PHONE_INTERNET, _("Phone & internet (line 25)")),
        (Category.DUES, _("Professional dues & memberships (line 27a)")),
        (Category.INSURANCE, _("Liability & business insurance (line 15)")),
        (Category.BANK_FEES, _("Bank & card processing fees (line 27a)")),
        (Category.LICENSES, _("Licenses & renewal fees (line 23)")),
        (Category.WEBSITE, _("Website / domain (line 8)")),
        (Category.ADVERTISING, _("Advertising / marketing (line 8)")),
        (Category.SOFTWARE, _("Software & subscriptions (line 18)")),
        (Category.PERSONAL_THERAPY, _("Personal therapy (training requirement)")),
        (Category.SUPERVISION, _("Clinical supervision (line 17)")),
        (Category.TRAINING, _("Continuing education / CEUs (line 27a)")),
        (Category.TRAINING_TRAVEL, _("Training travel & lodging (line 24a)")),
        (Category.PEER_CONSULTATION, _("Peer consultation group")),
        (Category.SUPPLIES, _("Office & therapy supplies (line 22)")),
        (Category.HARDWARE, _("Equipment (line 13 / Section 179)")),
        (Category.BOOKS, _("Books & publications")),
        (Category.CONFERENCES, _("Conferences")),
        (Category.OTHER, _("Other")),
    ]

    # Practice relationship
    practice = models.ForeignKey(
        "Practice",
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name=_("Practice"),
    )

    date = models.DateField(verbose_name=_("Date"))
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount"),
        help_text=_("Enter amount as a positive number"),
    )
    description = models.TextField(blank=True, verbose_name=_("Description"))
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default=Category.OTHER,
        verbose_name=_("Category"),
    )
    has_invoice = models.BooleanField(default=False, verbose_name=_("Invoice available"))
    is_tax_deductible = models.BooleanField(default=True, verbose_name=_("Tax deductible"))
    is_filed_in_tax_return = models.BooleanField(
        default=False, verbose_name=_("Filed in tax return")
    )

    # Practice-scoped manager
    objects = PracticeScopedManager()

    class Meta:
        ordering = ["-date"]
        verbose_name = _("Company Expense")
        verbose_name_plural = _("Company Expenses")
        indexes = [
            models.Index(fields=["date"], name="expense_date_idx"),
            models.Index(fields=["category"], name="expense_category_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.date} - {self.get_category_display()}: ${self.amount}"


def expense_attachment_upload_path(instance: "ExpenseReceipt", filename: str) -> str:
    """Store attachments under taxes/<year>/<slug> with enumeration for collisions."""
    from django.conf import settings

    expense = instance.expense
    year = expense.date.year if expense.date else "unknown"
    title = expense.description or Path(filename).stem
    stem = slugify(title)[:50] or "receipt"
    ext = Path(filename).suffix.lower()
    candidate = f"taxes/{year}/{stem}{ext}"
    media_root = Path(settings.MEDIA_ROOT)
    counter = 2
    while (media_root / candidate).exists():
        candidate = f"taxes/{year}/{stem} #{counter}{ext}"
        counter += 1
    return candidate


class ExpenseReceipt(models.Model):
    """A single file attachment (Beleg) for a CompanyExpense."""

    expense = models.ForeignKey(
        CompanyExpense,
        on_delete=models.CASCADE,
        related_name="receipts",
        verbose_name=_("Expense"),
    )
    file = models.FileField(
        upload_to=expense_attachment_upload_path,
        verbose_name=_("File"),
        help_text=_("PDF, JPG or PNG of the receipt / invoice"),
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        verbose_name = _("Receipt")
        verbose_name_plural = _("Receipts")

    def __str__(self) -> str:
        return f"{self.expense} — {Path(self.file.name or '').name}"


class TaxYearNote(TimestampedModel):
    """
    Per-year tax record: allocation note, and the annual settlement result.

    Stores things like "Revenue ratio 95/5 for 2025 — home office split accordingly."
    Also records the filed return's result (balance due or refund) once known.
    One record per practice per year; used as audit documentation.
    """

    practice = models.ForeignKey(
        "Practice",
        on_delete=models.CASCADE,
        related_name="tax_year_notes",
        verbose_name=_("Practice"),
    )
    year = models.PositiveSmallIntegerField(verbose_name=_("Tax year"), db_index=True)
    allocation_note = models.TextField(
        blank=True,
        verbose_name=_("Allocation note"),
        help_text=_(
            "Documented split key, e.g. "
            '"Revenue share 95/5 for 2025 — HO allowance and commuter allowance split accordingly."'
        ),
    )
    settlement_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Tax back payment / refund"),
        help_text=_(
            "Positive = back payment to the tax office, negative = refund from the tax office"
        ),
    )
    settlement_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Assessment date"),
        help_text=_("Date of the tax assessment notice"),
    )

    class Meta:
        unique_together = [("practice", "year")]
        ordering = ["-year"]
        verbose_name = _("Tax year note")
        verbose_name_plural = _("Tax year notes")

    def __str__(self) -> str:
        return f"{self.practice} — {self.year}"
