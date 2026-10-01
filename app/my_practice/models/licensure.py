"""Professional licenses held by the practitioner, one per state."""

from datetime import date, timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..us_states import US_STATE_CHOICES
from .base import PracticeScopedManager, TimestampedModel

# How far ahead a renewal shows up as "expiring soon" (dashboard, Focus Queue)
RENEWAL_WARNING_DAYS = 90


class ProviderLicense(TimestampedModel):
    """
    A state license (e.g. LPC) the practitioner holds.

    Counseling is regulated where the *client* is located during a session, so
    telehealth clients in another state need a license there. The client detail
    page warns when a client's state isn't covered by a current license.
    """

    practice = models.ForeignKey(
        "Practice",
        on_delete=models.CASCADE,
        related_name="licenses",
        verbose_name=_("Practice"),
    )
    state = models.CharField(max_length=2, choices=US_STATE_CHOICES, verbose_name=_("State"))
    license_type = models.CharField(
        max_length=30,
        default="LPC",
        verbose_name=_("License type"),
        help_text=_("e.g. LPC, LPC-S, LPCC"),
    )
    license_number = models.CharField(max_length=50, verbose_name=_("License number"))
    expiration_date = models.DateField(null=True, blank=True, verbose_name=_("Expiration date"))
    notes = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Notes"),
        help_text=_("e.g. CE hours required for renewal"),
    )

    objects = PracticeScopedManager()

    class Meta:
        ordering = ["state", "license_type"]
        verbose_name = _("Professional license")
        verbose_name_plural = _("Professional licenses")
        constraints = [
            models.UniqueConstraint(
                fields=["practice", "state", "license_type"],
                name="unique_license_per_state_and_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.license_type} {self.state} #{self.license_number}"

    def is_current(self, on: date | None = None) -> bool:
        """True unless the license has an expiration date that has passed."""
        on = on or timezone.localdate()
        return self.expiration_date is None or self.expiration_date >= on

    @property
    def is_expired(self) -> bool:
        return not self.is_current()

    @property
    def expires_soon(self) -> bool:
        """Current, but expiring within RENEWAL_WARNING_DAYS."""
        if self.expiration_date is None or self.is_expired:
            return False
        horizon = timezone.localdate() + timedelta(days=RENEWAL_WARNING_DAYS)
        return self.expiration_date <= horizon
