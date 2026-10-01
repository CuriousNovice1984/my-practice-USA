"""
Link Plaid items and import their transactions into the bank review pipeline.

Transactions go through the same BankStatementImporter.ingest_transaction() as
a CSV upload, so invoice matching, owner-draw detection, learned expense
categories and the review pages behave identically for both sources.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import Practice
from ..models.plaid import PlaidAccount, PlaidItem
from .bank_import import BankStatementImporter
from .plaid_client import PlaidClient, PlaidError

# Account types imported by default when an item is linked; credit cards and
# loans can be switched on per account on the Plaid page.
DEFAULT_IMPORT_TYPES = {"depository"}

RESULT_KEYS = ("total", "matched", "unmatched", "needs_review", "ignored")


def link_item(
    practice: Practice, public_token: str, institution_name: str, client: PlaidClient | None = None
) -> PlaidItem:
    """Exchange a Plaid Link public token and store the item with its accounts."""
    client = client or PlaidClient()
    access_token, item_id = client.exchange_public_token(public_token)
    accounts = client.get_accounts(access_token)
    with db_transaction.atomic():
        item = PlaidItem.objects.create(
            practice=practice,
            item_id=item_id,
            access_token=access_token,
            institution_name=institution_name[:200],
        )
        for account in accounts:
            PlaidAccount.objects.create(
                item=item,
                account_id=account["account_id"],
                name=(account.get("official_name") or account.get("name") or "")[:200],
                mask=account.get("mask") or "",
                subtype=account.get("subtype") or account.get("type") or "",
                import_enabled=account.get("type") in DEFAULT_IMPORT_TYPES,
            )
    return item


def _to_parsed(txn: dict[str, Any]) -> dict[str, Any]:
    """Convert a Plaid transaction into the importer's normalized dict.

    Plaid amounts are positive for money *leaving* the account, the opposite of
    the bank-statement convention the importer uses, so the sign flips.
    """
    posted = date.fromisoformat(txn["date"])
    authorized = txn.get("authorized_date")
    counterparties = txn.get("counterparties") or []
    payer_name = (
        txn.get("merchant_name")
        or (counterparties[0].get("name") if counterparties else None)
        or txn.get("name")
        or ""
    )
    return {
        "transaction_date": date.fromisoformat(authorized) if authorized else posted,
        "value_date": posted,
        "payer_name": payer_name[:200],
        "payer_account": "",
        "reference": txn.get("original_description") or txn.get("name") or "",
        "amount": -Decimal(str(txn["amount"])),
        "balance_after": None,
        "external_id": txn["transaction_id"],
    }


def sync_item(item: PlaidItem, client: PlaidClient | None = None) -> dict[str, Any]:
    """Pull new transactions for one item and ingest the posted ones.

    The cursor is saved only after every page has been ingested, so a failure
    mid-way re-fetches from the last good cursor next time; transaction IDs
    keep that retry from creating duplicates.
    """
    client = client or PlaidClient()
    accounts = {acc.account_id: acc for acc in item.accounts.filter(import_enabled=True)}
    importers: dict[str, BankStatementImporter] = {}
    totals: dict[str, Any] = dict.fromkeys(RESULT_KEYS, 0)
    totals["errors"] = []

    cursor = item.cursor
    try:
        while True:
            page = client.sync_transactions(item.access_token, cursor)
            for txn in page.get("added", []) + page.get("modified", []):
                account = accounts.get(txn.get("account_id"))
                # Pending transactions are re-issued under a new ID once they post
                if account is None or txn.get("pending"):
                    continue
                importer = importers.get(account.account_id)
                if importer is None:
                    importer = BankStatementImporter.for_account(item.practice, "")
                    # Label rows with the readable account name; for_account() would
                    # normalize it like a CSV account number
                    importer.source_account = account.source_label
                    importers[account.account_id] = importer
                importer.ingest_transaction(_to_parsed(txn), skip_negatives=False)
            cursor = page["next_cursor"]
            if not page.get("has_more"):
                break
    except PlaidError as exc:
        item.last_error = str(exc)[:300]
        item.save(update_fields=["last_error", "updated_at"])
        raise

    item.cursor = cursor
    item.last_synced_at = timezone.now()
    item.last_error = ""
    item.save(update_fields=["cursor", "last_synced_at", "last_error", "updated_at"])

    for importer in importers.values():
        for key in RESULT_KEYS:
            totals[key] += importer.results[key]
        totals["errors"].extend(importer.results["errors"])
    return totals


def sync_practice(practice: Practice, client: PlaidClient | None = None) -> dict[str, Any]:
    """Sync every linked item of a practice. Item failures are collected, not raised."""
    totals: dict[str, Any] = dict.fromkeys(RESULT_KEYS, 0)
    totals["errors"] = []
    for item in PlaidItem.objects.filter(practice=practice):
        try:
            result = sync_item(item, client)
        except PlaidError as exc:
            totals["errors"].append(f"{item}: {exc}")
            continue
        for key in RESULT_KEYS:
            totals[key] += result[key]
        totals["errors"].extend(result["errors"])
    return totals
