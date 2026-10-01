"""Helpers for the client forms portal."""

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from ..models.portal import PortalLink


def portal_url(request: HttpRequest, link: PortalLink) -> str:
    """Absolute URL a client opens to reach their upload page.

    Uses PORTAL_BASE_URL when set (the public Tailscale Funnel hostname — the
    practice itself is reached on a private tailnet name the client can't
    resolve), else the host the practitioner is currently using.
    """
    path = reverse("portal_home", kwargs={"token": link.token})
    base = settings.PORTAL_BASE_URL.rstrip("/")
    return f"{base}{path}" if base else request.build_absolute_uri(path)
