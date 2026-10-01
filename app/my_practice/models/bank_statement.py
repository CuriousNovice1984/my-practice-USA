"""Bank statement and transaction models"""

from enum import StrEnum

from django.db import models
from django.utils.translation import gettext_lazy

from .base import PracticeScopedManager


class BankTransaction(models.Model):
    """
    Bank transaction from a CSV import or a Plaid sync.

    Represents a single transaction line from the practice's bank account.
    Used for automatic invoice payment matching and reconciliation.
    """

    class Confidence(StrEnum):
        EXACT = "exact"
        FUZZY = "fuzzy"
        MANUAL = "manual"
        IGNORED = "ignored"
        UNMATCHED = "unmatched"
        AUTO_WITHDRAWAL = "auto-withdrawal"
        AUTO_EXPENSE = "auto-expense"
        AUTO_CONTRIBUTION = "auto-contribution"
        AUTO_CORRECTION = "auto-correction"

    CONFIDENCE_CHOICES = [
        (Confidence.EXACT, gettext_lazy("Exact Match")),
        (Confidence.FUZZY, gettext_lazy("Fuzzy Match (±$5)")),
        (Confidence.MANUAL, gettext_lazy("Manual Assignment")),
        (Confidence.IGNORED, gettext_lazy("Ignored (Expense/Duplicate)")),
        (Confidence.UNMATCHED, gettext_lazy("Unmatched")),
        (Confidence.AUTO_WITHDRAWAL, gettext_lazy("Auto-Created Withdrawal")),
        (Confidence.AUTO_EXPENSE, gettext_lazy("Auto-Created Expense")),
        (Confidence.AUTO_CONTRIBUTION, gettext_lazy("Auto-Created Owner Contribution")),
        (Confidence.AUTO_CORRECTION, gettext_lazy("Auto-Created Correction")),
    ]

    # Practice relationship
    practice = models.ForeignKey(
        "Practice",
        on_delete=models.CASCADE,
        related_name="bank_transactions",
        verbose_name=gettext_lazy("Practice"),
    )

    # Transaction details (from CSV)
    transaction_date = models.DateField(
        verbose_name=gettext_lazy("Booking date"),
        help_text=gettext_lazy("Transaction booking date"),
    )
    value_date = models.DateField(
        verbose_name=gettext_lazy("Posted date"),
        help_text=gettext_lazy("Date the transaction posted (same as the date if unknown)"),
    )
    payer_name = models.CharField(
        max_length=200,
        verbose_name=gettext_lazy("Payer/payee name"),
        help_text=gettext_lazy("Name of payer/payee"),
    )
    payer_account = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=gettext_lazy("Payer/payee account"),
    )
    reference = models.TextField(
        verbose_name=gettext_lazy("Payment reference"),
        help_text=gettext_lazy("Payment reference text"),
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=gettext_lazy("Amount"),
        help_text=gettext_lazy("Transaction amount (positive=income, negative=expense)"),
    )
    balance_after = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=gettext_lazy("Balance after transaction"),
        help_text=gettext_lazy("Account balance after transaction"),
    )

    # Matching information
    matched_invoice = models.ForeignKey(
        "Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_transactions",
        verbose_name=gettext_lazy("Matched invoice"),
        help_text=gettext_lazy("Invoice this transaction was matched to"),
    )
    match_confidence = models.CharField(
        max_length=20,
        choices=CONFIDENCE_CHOICES,
        default="unmatched",
        verbose_name=gettext_lazy("Match confidence"),
    )
    extracted_invoice_number = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=gettext_lazy("Extracted invoice number"),
        help_text=gettext_lazy("Invoice number extracted from reference text"),
    )

    # Metadata
    imported_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=gettext_lazy("Imported on"),
    )
    processed = models.BooleanField(
        default=False,
        verbose_name=gettext_lazy("Processed"),
        help_text=gettext_lazy("Whether transaction has been processed/matched"),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=gettext_lazy("Notes"),
        help_text=gettext_lazy("Manual notes about this transaction"),
    )

    # Links to auto-created financial records
    linked_expense = models.ForeignKey(
        "CompanyExpense",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_transactions",
        verbose_name=gettext_lazy("Linked expense"),
        help_text=gettext_lazy(
            "CompanyExpense auto-created or manually assigned for this transaction"
        ),
    )
    linked_withdrawal = models.ForeignKey(
        "CompanyWithdrawal",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_transactions",
        verbose_name=gettext_lazy("Linked withdrawal"),
        help_text=gettext_lazy(
            "CompanyWithdrawal auto-created or manually assigned for this transaction"
        ),
    )

    # Source
    source_account = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=gettext_lazy("Account"),
        help_text=gettext_lazy("Bank account the transaction belongs to"),
    )
    external_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name=gettext_lazy("External ID"),
        help_text=gettext_lazy(
            "Transaction ID from the bank connection (Plaid), for deduplication"
        ),
    )

    # Practice-scoped manager
    objects = PracticeScopedManager()

    class Meta:
        unique_together = [["practice", "transaction_date", "amount", "reference"]]
        ordering = ["-transaction_date"]
        verbose_name = gettext_lazy("Bank Transaction")
        verbose_name_plural = gettext_lazy("Bank Transactions")
        indexes = [
            models.Index(fields=["practice", "transaction_date"]),
            models.Index(fields=["practice", "processed"]),
            models.Index(fields=["practice", "match_confidence"]),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_date} - {self.payer_name}: ${self.amount}"

    @property
    def is_income(self) -> bool:
        """Check if transaction is income (positive amount)"""
        return self.amount > 0

    @property
    def is_expense(self) -> bool:
        """Check if transaction is expense (negative amount)"""
        return self.amount < 0

    @property
    def is_matched(self) -> bool:
        """Check if transaction is matched to an invoice"""
        return self.matched_invoice is not None
