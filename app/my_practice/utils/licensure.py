"""Licensure checks: is the practitioner licensed where a client is located?"""

from datetime import date

from django.utils import timezone

from ..models import Client, Practice, ProviderLicense


def licensed_states(practice: Practice, on: date | None = None) -> set[str]:
    """States in which the practice holds a current (unexpired) license."""
    on = on or timezone.localdate()
    return {
        lic.state for lic in ProviderLicense.objects.filter(practice=practice) if lic.is_current(on)
    }


def client_licensure_gap(client: Client) -> str | None:
    """The client's state if no current license covers it, else None.

    Returns None when the client's state is unknown — there is nothing to check.
    """
    if not client.state:
        return None
    if client.state in licensed_states(client.practice):
        return None
    return client.state


def licenses_needing_attention(practice: Practice) -> list[ProviderLicense]:
    """Licenses that have expired or expire within the renewal warning window."""
    return [
        lic
        for lic in ProviderLicense.objects.filter(practice=practice)
        if lic.is_expired or lic.expires_soon
    ]
