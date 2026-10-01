"""Tests for the Plaid bank connection (client, sync into bank review, views).

Plaid's HTTP API is never called: PlaidClient is replaced by a fake that
returns canned payloads in Plaid's documented response shapes.
"""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client as TestClient
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import (
    BankTransaction,
    Client,
    CompanyExpense,
    Invoice,
    InvoiceItem,
    Practice,
    ServiceType,
    Session,
    UserPractice,
)
from ..models.plaid import PlaidAccount, PlaidItem
from ..utils.plaid_client import PlaidClient, PlaidError
from ..utils.plaid_sync import _to_parsed, link_item, sync_item

PLAID_SETTINGS = {"PLAID_CLIENT_ID": "test-client", "PLAID_SECRET": "test-secret"}


def plaid_txn(transaction_id, amount, name, account_id="acc-checking", **extra):
    """A transaction as /transactions/sync returns it (positive amount = money out)."""
    txn = {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "amount": amount,
        "date": "2026-03-05",
        "authorized_date": "2026-03-04",
        "name": name,
        "merchant_name": None,
        "original_description": None,
        "pending": False,
        "counterparties": [],
    }
    txn.update(extra)
    return txn


class FakePlaid:
    """Stands in for PlaidClient, serving /transactions/sync pages in order."""

    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.cursors_seen = []

    def exchange_public_token(self, public_token):
        return "access-sandbox-123", "item-123"

    def get_accounts(self, access_token):
        return [
            {
                "account_id": "acc-checking",
                "name": "Business Checking",
                "mask": "4321",
                "type": "depository",
                "subtype": "checking",
                "official_name": None,
            },
            {
                "account_id": "acc-card",
                "name": "Credit Card",
                "mask": "9999",
                "type": "credit",
                "subtype": "credit card",
                "official_name": None,
            },
        ]

    def sync_transactions(self, access_token, cursor):
        self.cursors_seen.append(cursor)
        return self.pages.pop(0)


@override_settings(FERNET_KEY="7zIJPIlZkdMSPifNsPuNBjIAIqiUkFHmRJN8HGG8ytQ=")  # gitleaks:allow
class PlaidTestBase(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Test Practice", slug="plaid-test")
        self.client_obj = Client.objects.create(
            practice=self.practice, client_code="AS", full_name="Anna Schmidt"
        )
        self.invoice = Invoice.objects.create(
            practice=self.practice,
            client=self.client_obj,
            invoice_number="AS-1",
            status="sent",
            invoice_date=date(2026, 3, 1),
        )
        service_type = ServiceType.objects.create(code="plaid_60", name="Session")
        InvoiceItem.objects.create(
            invoice=self.invoice,
            service_type=service_type,
            session=Session.objects.create(client=self.client_obj, session_date=date(2026, 3, 1)),
            rate=Decimal("150.00"),
            quantity=1,
        )

    def linked_item(self, pages=None):
        fake = FakePlaid(pages)
        item = link_item(self.practice, "public-sandbox-xyz", "Test Bank", client=fake)
        return item, fake


class LinkItemTest(PlaidTestBase):
    def test_stores_item_and_accounts(self):
        item, _ = self.linked_item()
        self.assertEqual(item.item_id, "item-123")
        self.assertEqual(item.institution_name, "Test Bank")
        self.assertEqual(item.access_token, "access-sandbox-123")
        accounts = {a.account_id: a for a in item.accounts.all()}
        self.assertTrue(accounts["acc-checking"].import_enabled)
        self.assertFalse(accounts["acc-card"].import_enabled)  # credit off by default
        self.assertEqual(str(accounts["acc-checking"]), "Business Checking …4321")

    def test_access_token_encrypted_at_rest(self):
        item, _ = self.linked_item()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT access_token FROM my_practice_plaiditem WHERE id = %s", [item.pk]
            )
            raw = cursor.fetchone()[0]
        self.assertNotIn("access-sandbox-123", raw)


class ToParsedTest(TestCase):
    def test_sign_flips_and_dates(self):
        parsed = _to_parsed(plaid_txn("t1", 150.0, "Zelle from Anna Schmidt AS-1"))
        self.assertEqual(parsed["amount"], Decimal("-150.0"))
        self.assertEqual(parsed["transaction_date"], date(2026, 3, 4))  # authorized
        self.assertEqual(parsed["value_date"], date(2026, 3, 5))  # posted
        self.assertEqual(parsed["external_id"], "t1")

    def test_payer_prefers_merchant_then_counterparty(self):
        txn = plaid_txn("t1", 10, "RAW", counterparties=[{"name": "Office Depot"}])
        self.assertEqual(_to_parsed(txn)["payer_name"], "Office Depot")
        txn["merchant_name"] = "Staples"
        self.assertEqual(_to_parsed(txn)["payer_name"], "Staples")

    def test_reference_prefers_original_description(self):
        txn = plaid_txn("t1", -150, "Zelle", original_description="ZELLE FROM A SCHMIDT AS-1")
        self.assertEqual(_to_parsed(txn)["reference"], "ZELLE FROM A SCHMIDT AS-1")


class SyncItemTest(PlaidTestBase):
    def test_incoming_payment_marks_invoice_paid(self):
        page = {
            "added": [plaid_txn("t1", -150.0, "Zelle payment from Anna Schmidt for AS-1")],
            "modified": [],
            "removed": [],
            "next_cursor": "cursor-1",
            "has_more": False,
        }
        item, fake = self.linked_item([page])
        results = sync_item(item, client=fake)

        self.assertEqual(results["matched"], 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        txn = BankTransaction.objects.get()
        self.assertEqual(txn.external_id, "t1")
        self.assertEqual(txn.source_account, "Business Checking …4321")
        item.refresh_from_db()
        self.assertEqual(item.cursor, "cursor-1")
        self.assertIsNotNone(item.last_synced_at)

    def test_outgoing_payment_becomes_expense(self):
        page = {
            "added": [plaid_txn("t2", 42.5, "OFFICE DEPOT", merchant_name="Office Depot")],
            "next_cursor": "c",
            "has_more": False,
        }
        item, fake = self.linked_item([page])
        results = sync_item(item, client=fake)
        self.assertEqual(results["needs_review"], 1)
        self.assertEqual(CompanyExpense.objects.get().amount, Decimal("42.50"))

    def test_skips_pending_and_disabled_accounts(self):
        page = {
            "added": [
                plaid_txn("t3", -150.0, "AS-1", pending=True),
                plaid_txn("t4", 20.0, "Card purchase", account_id="acc-card"),
            ],
            "next_cursor": "c",
            "has_more": False,
        }
        item, fake = self.linked_item([page])
        sync_item(item, client=fake)
        self.assertEqual(BankTransaction.objects.count(), 0)

    def test_pages_until_has_more_is_false_and_resumes_from_cursor(self):
        pages = [
            {"added": [plaid_txn("t5", 10, "A")], "next_cursor": "c1", "has_more": True},
            {"added": [plaid_txn("t6", 11, "B")], "next_cursor": "c2", "has_more": False},
        ]
        item, fake = self.linked_item(pages)
        sync_item(item, client=fake)
        self.assertEqual(fake.cursors_seen, ["", "c1"])
        self.assertEqual(BankTransaction.objects.count(), 2)

        fake.pages = [{"added": [], "next_cursor": "c3", "has_more": False}]
        item.refresh_from_db()
        sync_item(item, client=fake)
        self.assertEqual(fake.cursors_seen[-1], "c2")

    def test_resync_does_not_duplicate(self):
        page = {"added": [plaid_txn("t7", 10, "A")], "next_cursor": "c", "has_more": False}
        item, fake = self.linked_item([page, dict(page)])
        sync_item(item, client=fake)
        item.cursor = ""  # simulate a lost cursor
        sync_item(item, client=fake)
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_error_recorded_and_cursor_kept(self):
        item, fake = self.linked_item()
        item.cursor = "good-cursor"
        item.save()
        fake.sync_transactions = MagicMock(side_effect=PlaidError("ITEM_LOGIN_REQUIRED"))
        with self.assertRaises(PlaidError):
            sync_item(item, client=fake)
        item.refresh_from_db()
        self.assertEqual(item.cursor, "good-cursor")
        self.assertIn("ITEM_LOGIN_REQUIRED", item.last_error)


class PlaidClientTest(TestCase):
    @override_settings(PLAID_CLIENT_ID="", PLAID_SECRET="")
    def test_unconfigured_raises(self):
        with self.assertRaises(PlaidError):
            PlaidClient()

    @override_settings(**PLAID_SETTINGS, PLAID_ENV="sandbox")
    @patch("my_practice.utils.plaid_client.requests.post")
    def test_posts_credentials_and_surfaces_errors(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=400,
            json=lambda: {"error_code": "INVALID_FIELD", "error_message": "bad"},
        )
        with self.assertRaises(PlaidError) as ctx:
            PlaidClient().get_accounts("access-x")
        self.assertEqual(ctx.exception.code, "INVALID_FIELD")
        url = mock_post.call_args.args[0]
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(url, "https://sandbox.plaid.com/accounts/get")
        self.assertEqual(body["client_id"], "test-client")


@override_settings(**PLAID_SETTINGS)
class PlaidViewsTest(PlaidTestBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="plaiduser", password="testpass123")
        UserPractice.objects.create(user=self.user, practice=self.practice, is_owner=True)
        self.http = TestClient()
        self.http.login(username="plaiduser", password="testpass123")
        session = self.http.session
        session["current_practice_slug"] = self.practice.slug
        session.save()

    def test_landing_page(self):
        self.linked_item()
        response = self.http.get(reverse("plaid_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connect a bank")
        self.assertContains(response, "Business Checking …4321")
        self.assertNotContains(response, "access-sandbox-123")

    @override_settings(PLAID_CLIENT_ID="", PLAID_SECRET="")
    def test_landing_page_when_not_configured(self):
        response = self.http.get(reverse("plaid_home"))
        self.assertContains(response, "Plaid isn't set up yet")

    @patch("my_practice.views.plaid_views.PlaidClient")
    def test_link_token(self, mock_client):
        mock_client.return_value.create_link_token.return_value = "link-sandbox-abc"
        response = self.http.post(reverse("plaid_link_token"))
        self.assertEqual(response.json(), {"link_token": "link-sandbox-abc"})

    @patch("my_practice.views.plaid_views.link_item")
    def test_exchange(self, mock_link):
        mock_link.return_value = PlaidItem(institution_name="Test Bank")
        response = self.http.post(
            reverse("plaid_exchange"),
            data=json.dumps({"public_token": "public-x", "institution": {"name": "Test Bank"}}),
            content_type="application/json",
        )
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(mock_link.call_args.args[1:], ("public-x", "Test Bank"))

    def test_exchange_rejects_bad_payload(self):
        response = self.http.post(
            reverse("plaid_exchange"), data="nope", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    @patch("my_practice.views.plaid_views.sync_practice")
    def test_sync_redirects_to_review(self, mock_sync):
        mock_sync.return_value = {
            "total": 3,
            "matched": 1,
            "unmatched": 1,
            "needs_review": 1,
            "ignored": 0,
            "errors": [],
        }
        response = self.http.post(reverse("plaid_sync"))
        self.assertRedirects(response, reverse("bank_review"))

    def test_toggle_account(self):
        item, _ = self.linked_item()
        account = item.accounts.get(account_id="acc-card")
        self.http.post(reverse("plaid_toggle_account", args=[account.pk]))
        account.refresh_from_db()
        self.assertTrue(account.import_enabled)

    @patch("my_practice.views.plaid_views.PlaidClient")
    def test_remove_keeps_imported_transactions(self, mock_client):
        item, fake = self.linked_item(
            [{"added": [plaid_txn("t9", 5, "X")], "next_cursor": "c", "has_more": False}]
        )
        sync_item(item, client=fake)
        response = self.http.post(reverse("plaid_remove", args=[item.pk]))
        self.assertRedirects(response, reverse("plaid_home"))
        self.assertFalse(PlaidItem.objects.exists())
        self.assertFalse(PlaidAccount.objects.exists())
        self.assertEqual(BankTransaction.objects.count(), 1)
        mock_client.return_value.remove_item.assert_called_once()

    def test_other_practice_cannot_toggle(self):
        item, _ = self.linked_item()
        other = Practice.objects.create(name="Other", slug="plaid-other")
        item.practice = other
        item.save()
        account = item.accounts.first()
        response = self.http.post(reverse("plaid_toggle_account", args=[account.pk]))
        self.assertEqual(response.status_code, 404)


@override_settings(
    **PLAID_SETTINGS, FERNET_KEY="7zIJPIlZkdMSPifNsPuNBjIAIqiUkFHmRJN8HGG8ytQ="
)  # gitleaks:allow
class PlaidSyncCommandTest(PlaidTestBase):
    @patch("my_practice.management.commands.plaid_sync.sync_practice")
    def test_runs_for_practices_with_items(self, mock_sync):
        self.linked_item()
        mock_sync.return_value = {
            "total": 0,
            "matched": 0,
            "unmatched": 0,
            "needs_review": 0,
            "ignored": 0,
            "errors": [],
        }
        call_command("plaid_sync", stdout=MagicMock())
        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.args[0], self.practice)
