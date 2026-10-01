"""Bank connections via Plaid: linked institutions (items) and their accounts."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from ..fields import EncryptedCharField
from .base import PracticeScopedManager, TimestampedModel


class PlaidItem(TimestampedModel):
    """One linked bank login (a Plaid "Item"), holding the encrypted access token."""

    practice = models.ForeignKey(
        "Practice",
        on_delete=models.CASCADE,
        related_name="plaid_items",
        verbose_name=_("Practice"),
    )
    item_id = models.CharField(max_length=100, unique=True, verbose_name=_("Plaid item ID"))
    # A bearer credential for the account's transaction history — encrypted at
    # rest like clinical notes, so a database dump alone can't use it.
    access_token = EncryptedCharField(verbose_name=_("Access token"))
    institution_name = models.CharField(max_length=200, blank=True, verbose_name=_("Institution"))
    # Plaid /transactions/sync cursor: everything before it has been imported.
    cursor = models.TextField(blank=True, verbose_name=_("Sync cursor"))
    last_synced_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Last synced"))
    last_error = models.CharField(max_length=300, blank=True, verbose_name=_("Last error"))

    objects = PracticeScopedManager()

    class Meta:
        ordering = ["institution_name"]
        verbose_name = _("Bank connection")
        verbose_name_plural = _("Bank connections")

    def __str__(self) -> str:
        return self.institution_name or self.item_id


class PlaidAccount(models.Model):
    """An account under a linked item. Only accounts with import enabled are synced."""

    item = models.ForeignKey(
        PlaidItem,
        on_delete=models.CASCADE,
        related_name="accounts",
        verbose_name=_("Bank connection"),
    )
    account_id = models.CharField(max_length=100, unique=True, verbose_name=_("Plaid account ID"))
    name = models.CharField(max_length=200, verbose_name=_("Name"))
    mask = models.CharField(max_length=10, blank=True, verbose_name=_("Last digits"))
    subtype = models.CharField(max_length=50, blank=True, verbose_name=_("Type"))
    import_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Import transactions"),
        help_text=_("Turn off for accounts that aren't the practice's business accounts"),
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("Bank account")
        verbose_name_plural = _("Bank accounts")

    def __str__(self) -> str:
        return f"{self.name} …{self.mask}" if self.mask else self.name

    @property
    def source_label(self) -> str:
        """How transactions from this account are labelled (BankTransaction.source_account)."""
        return str(self)
