"""
Minimal Plaid API client (Link token, token exchange, accounts, transactions sync).

Talks to Plaid's REST API with `requests` rather than the plaid-python SDK — the
app uses five endpoints, and this keeps the dependency surface and the
generated-code churn out of the repo. Credentials come from settings
(PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV); see .env.example.
"""

from typing import Any

import requests
from django.conf import settings

PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
REQUEST_TIMEOUT = 30


class PlaidError(Exception):
    """A Plaid API call failed. ``code`` is Plaid's error_code when it sent one."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def plaid_configured() -> bool:
    return bool(settings.PLAID_CLIENT_ID and settings.PLAID_SECRET)


class PlaidClient:
    def __init__(self) -> None:
        if not plaid_configured():
            raise PlaidError("Plaid is not configured: set PLAID_CLIENT_ID and PLAID_SECRET.")
        env = settings.PLAID_ENV
        if env not in PLAID_HOSTS:
            raise PlaidError(f"Unknown PLAID_ENV {env!r}; use 'sandbox' or 'production'.")
        self.base_url = PLAID_HOSTS[env]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "client_id": settings.PLAID_CLIENT_ID,
            "secret": settings.PLAID_SECRET,
            **payload,
        }
        try:
            response = requests.post(f"{self.base_url}{path}", json=body, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise PlaidError(f"Could not reach Plaid: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise PlaidError(
                f"Unexpected response from Plaid (HTTP {response.status_code})"
            ) from exc
        if response.status_code != 200:
            message = data.get("display_message") or data.get("error_message") or "Plaid error"
            raise PlaidError(message, code=data.get("error_code", ""))
        return data

    def create_link_token(self, user_id: str) -> str:
        data = self._post(
            "/link/token/create",
            {
                "user": {"client_user_id": user_id},
                "client_name": "Practice Management",
                "products": ["transactions"],
                "country_codes": ["US"],
                "language": "en",
            },
        )
        return data["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        """Return (access_token, item_id) for a public token from Plaid Link."""
        data = self._post("/item/public_token/exchange", {"public_token": public_token})
        return data["access_token"], data["item_id"]

    def get_accounts(self, access_token: str) -> list[dict[str, Any]]:
        return self._post("/accounts/get", {"access_token": access_token})["accounts"]

    def sync_transactions(self, access_token: str, cursor: str) -> dict[str, Any]:
        """One page of /transactions/sync: added, modified, removed, next_cursor, has_more."""
        payload: dict[str, Any] = {
            "access_token": access_token,
            "count": 500,
            # The raw bank description is where Zelle/ACH memos (and invoice numbers) live
            "options": {"include_original_description": True},
        }
        if cursor:
            payload["cursor"] = cursor
        return self._post("/transactions/sync", payload)

    def remove_item(self, access_token: str) -> None:
        self._post("/item/remove", {"access_token": access_token})
