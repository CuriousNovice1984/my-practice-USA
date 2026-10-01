"""Client forms portal: blank forms to hand out, and private upload links."""

import hashlib
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..fields import EncryptedCharField
from .base import TimestampedModel
from .client import ClientDocument

if TYPE_CHECKING:
    from .client import Client

# A client can upload at most this many files through one link — bounds what a
# leaked link could be used to dump into the practice's storage.
MAX_UPLOADS_PER_LINK = 25


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PracticeForm(TimestampedModel):
    """A blank form (intake packet, informed consent, …) clients download from the portal."""

    practice = models.ForeignKey(
        "Practice",
        on_delete=models.CASCADE,
        related_name="portal_forms",
        verbose_name=_("Practice"),
    )
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.CharField(
        max_length=300,
        blank=True,
        verbose_name=_("Instructions"),
        help_text=_("Shown to the client, e.g. 'Please sign page 3'"),
    )
    document_type = models.CharField(
        max_length=20,
        choices=ClientDocument.DOC_TYPE_CHOICES,
        default=ClientDocument.DocumentType.OTHER,
        verbose_name=_("Document type"),
        help_text=_("Completed uploads of this form are filed under this type"),
    )
    file = models.FileField(upload_to="practice_forms/", verbose_name=_("File"))
    active = models.BooleanField(default=True, verbose_name=_("Offered in the portal"))
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name=_("Order"))

    class Meta:
        ordering = ["sort_order", "title"]
        verbose_name = _("Portal form")
        verbose_name_plural = _("Portal forms")

    def __str__(self) -> str:
        return self.title


class PortalLink(TimestampedModel):
    """
    A private, expiring link that lets one client upload documents without an account.

    Looked up by the SHA-256 of the token so the database index holds no usable
    secret; the token itself is kept Fernet-encrypted so the practitioner can
    copy the link again later.
    """

    client = models.ForeignKey(
        "Client",
        on_delete=models.CASCADE,
        related_name="portal_links",
        verbose_name=_("Client"),
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    token = EncryptedCharField(editable=False)
    expires_at = models.DateTimeField(verbose_name=_("Expires"))
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Revoked"))
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Last used"))
    upload_count = models.PositiveSmallIntegerField(default=0, verbose_name=_("Files uploaded"))

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Portal link")
        verbose_name_plural = _("Portal links")

    def __str__(self) -> str:
        return f"{self.client.client_code} portal link"

    @classmethod
    def create_for(cls, client: "Client", days: int) -> "PortalLink":
        token = secrets.token_urlsafe(32)
        return cls.objects.create(
            client=client,
            token=token,
            token_hash=hash_token(token),
            expires_at=timezone.now() + timedelta(days=days),
        )

    @classmethod
    def find_active(cls, token: str) -> "PortalLink | None":
        """The usable link for ``token``, or None if unknown, expired or revoked."""
        link = (
            cls.objects.select_related("client__practice")
            .filter(token_hash=hash_token(token))
            .first()
        )
        return link if link and link.is_active else None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @property
    def uploads_remaining(self) -> int:
        return max(MAX_UPLOADS_PER_LINK - self.upload_count, 0)
