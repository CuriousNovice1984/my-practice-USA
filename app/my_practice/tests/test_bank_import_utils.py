"""
Tests for BankStatementImporter utility class.

Covers: CSV parsing, invoice number extraction, invoice matching,
withdrawal/expense auto-detection, duplicate prevention, and end-to-end CSV processing.
"""

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ..models import (
    BankTransaction,
    Client,
    ClientAlias,
    CompanyExpense,
    CompanyWithdrawal,
    ExpenseCategoryRule,
    Invoice,
    InvoiceItem,
    Practice,
    ServiceType,
    Session,
)
from ..utils import BankStatementImporter, build_counterparty_key

PRACTICE_ACCOUNT = "CHK4321"
PRIVATE_ACCOUNT = "CHK9876"

CSV_HEADER = ["Account", "Date", "Posted", "Payee", "Payee Account", "Amount", "Balance", "Memo"]


def _csv_bytes(rows, account=PRACTICE_ACCOUNT, delimiter=","):
    """Render rows as a US-format bank CSV (MM/DD/YYYY dates, 1,234.56 amounts)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter)
    writer.writerow(CSV_HEADER)
    for r in rows:
        writer.writerow(
            [
                account,
                r.get("date", "01/15/2026"),
                r.get("date", "01/15/2026"),
                r.get("payer", "Test Payer"),
                r.get("payer_account", ""),
                r.get("amount", "90.00"),
                "1,000.00",
                r.get("ref", "Transfer"),
            ]
        )
    return buffer.getvalue().encode("utf-8")


def _make_importer(practice, rows, account=PRACTICE_ACCOUNT):
    """Build a BankStatementImporter with a fake CSV file."""
    csv_file = SimpleUploadedFile("test.csv", _csv_bytes(rows, account), content_type="text/csv")
    return BankStatementImporter(csv_file, practice)


def _make_practice(**kwargs):
    defaults = {
        "name": "Test Practice",
        "slug": "bank-util-test",
        "title": "Therapist",
        "email": "test@example.com",
        "csv_column_value_date": "Posted",
        "csv_column_payer_name": "Payee",
        "csv_column_payer_account": "Payee Account",
        "csv_column_reference": "Memo",
        "csv_column_balance": "Balance",
        "csv_column_account": "Account",
    }
    defaults.update(kwargs)
    return Practice.objects.create(**defaults)


def _make_invoice_item(invoice, practice, client_obj, rate=Decimal("90.00"), duration=60):
    """Create the minimum required objects for an InvoiceItem."""
    service_type, _ = ServiceType.objects.get_or_create(
        code=f"test_therapy_{duration}",
        defaults={"practice": practice, "name": f"Therapy {duration}min"},
    )
    session = Session.objects.create(
        client=client_obj,
        session_date=date(2026, 1, 1),
        duration=duration,
    )
    return InvoiceItem.objects.create(
        invoice=invoice,
        service_type=service_type,
        session=session,
        rate=rate,
        quantity=1,
    )


# ── parse_amount ──────────────────────────────────────────────────────────────


class ParseAmountTest(TestCase):
    def setUp(self):
        self.practice = _make_practice(slug="parse-amount")
        self.importer = _make_importer(self.practice, [])

    def test_positive(self):
        self.assertEqual(self.importer.parse_amount("90.00"), Decimal("90.00"))

    def test_negative(self):
        self.assertEqual(self.importer.parse_amount("-300.00"), Decimal("-300.00"))

    def test_parenthesized_is_negative(self):
        self.assertEqual(self.importer.parse_amount("(300.00)"), Decimal("-300.00"))

    def test_thousands_separator_and_symbol(self):
        self.assertEqual(self.importer.parse_amount("$1,234.56"), Decimal("1234.56"))

    def test_invalid_raises(self):
        with self.assertRaises(InvalidOperation):
            self.importer.parse_amount("not-a-number")


# ── parse_date ────────────────────────────────────────────────────────────────


class ParseDateTest(TestCase):
    def setUp(self):
        self.practice = _make_practice(slug="parse-date")
        self.importer = _make_importer(self.practice, [])

    def test_us_format(self):
        self.assertEqual(self.importer.parse_date("02/14/2026"), date(2026, 2, 14))

    def test_two_digit_year(self):
        self.assertEqual(self.importer.parse_date("02/14/26"), date(2026, 2, 14))

    def test_iso_format(self):
        self.assertEqual(self.importer.parse_date("2026-02-14"), date(2026, 2, 14))

    def test_day_first_format_raises(self):
        with self.assertRaises(ValueError):
            self.importer.parse_date("14.02.2026")


# ── extract_invoice_number ────────────────────────────────────────────────────


class ExtractInvoiceNumberTest(TestCase):
    def setUp(self):
        self.practice = _make_practice(slug="extract-inv")
        self.importer = _make_importer(self.practice, [])

    def test_direct_code(self):
        self.assertEqual(self.importer.extract_invoice_number("XX-1"), "XX-1")

    def test_direct_code_longer(self):
        self.assertEqual(self.importer.extract_invoice_number("ABCD-123"), "ABCD-123")

    def test_inv_hash_keyword(self):
        self.assertEqual(self.importer.extract_invoice_number("Inv #YY-2"), "YY-2")

    def test_invoice_keyword(self):
        self.assertEqual(self.importer.extract_invoice_number("Invoice No. AB-3"), "AB-3")

    def test_code_inside_zelle_memo(self):
        self.assertEqual(
            self.importer.extract_invoice_number("Zelle payment from M Schmidt for CD-4"), "CD-4"
        )

    def test_uppercase_normalised(self):
        self.assertEqual(self.importer.extract_invoice_number("ab-12"), "AB-12")

    def test_no_match_time(self):
        self.assertIsNone(self.importer.extract_invoice_number("Wed 9-10"))

    def test_no_match_plain_text(self):
        self.assertIsNone(self.importer.extract_invoice_number("Transfer office rent"))

    def test_no_match_single_letter(self):
        # Single letter codes must not be extracted (min 2 letters)
        self.assertIsNone(self.importer.extract_invoice_number("A-1"))


# ── find_matching_invoice ─────────────────────────────────────────────────────


class FindMatchingInvoiceTest(TestCase):
    def setUp(self):
        self.practice = _make_practice(slug="find-invoice")
        self.client_obj = Client.objects.create(
            practice=self.practice,
            full_name="Anna Schmidt",
            client_code="AS",
        )
        self.invoice = Invoice.objects.create(
            practice=self.practice,
            client=self.client_obj,
            invoice_number="AS-1",
            status="sent",
            invoice_date=date(2026, 1, 1),
        )
        _make_invoice_item(self.invoice, self.practice, self.client_obj)
        self.importer = _make_importer(self.practice, [])

    def test_exact_name_match(self):
        result = self.importer.find_matching_invoice("AS-1", Decimal("90.00"), "Anna Schmidt")
        self.assertIsNotNone(result)
        invoice, confidence = result
        self.assertEqual(invoice, self.invoice)
        self.assertEqual(confidence, "exact")

    def test_different_name_still_exact(self):
        # Name mismatch but no alias → still returns exact (user can add alias later)
        result = self.importer.find_matching_invoice("AS-1", Decimal("90.00"), "Unknown")
        self.assertIsNotNone(result)
        _, confidence = result
        self.assertEqual(confidence, "exact")

    def test_fuzzy_match_via_alias(self):
        ClientAlias.objects.create(client=self.client_obj, alias_name="A. Schmidt")
        result = self.importer.find_matching_invoice("AS-1", Decimal("90.00"), "A. Schmidt")
        self.assertIsNotNone(result)
        _, confidence = result
        self.assertEqual(confidence, "fuzzy")

    def test_amount_mismatch_returns_none(self):
        result = self.importer.find_matching_invoice("AS-1", Decimal("80.00"), "Anna Schmidt")
        self.assertIsNone(result)

    def test_wrong_invoice_number(self):
        result = self.importer.find_matching_invoice("XX-99", Decimal("90.00"), "Anna Schmidt")
        self.assertIsNone(result)

    def test_paid_invoice_not_matched(self):
        self.invoice.status = "paid"
        self.invoice.save()
        result = self.importer.find_matching_invoice("AS-1", Decimal("90.00"), "Anna Schmidt")
        self.assertIsNone(result)


# ── detect_and_create_financial_record ───────────────────────────────────────


class DetectFinancialRecordTest(TestCase):
    def setUp(self):
        self.practice = _make_practice(
            slug="detect-financial",
            private_bank_account=PRIVATE_ACCOUNT,
        )
        self.importer = _make_importer(self.practice, [])
        self.txn_date = date(2026, 2, 1)

    def test_private_account_match_creates_withdrawal(self):
        result = self.importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-300.00"), "Owner draw", payer_account=PRIVATE_ACCOUNT
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "CompanyWithdrawal")
        self.assertEqual(CompanyWithdrawal.objects.filter(practice=self.practice).count(), 1)

    def test_withdrawal_category_private_transfer(self):
        result = self.importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-300.00"), "Transfer", payer_account=PRIVATE_ACCOUNT
        )
        self.assertEqual(result["record"].category, "private_transfer")

    def test_correction_keyword_sets_category(self):
        result = self.importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-50.00"), "Reversal correction", payer_account=PRIVATE_ACCOUNT
        )
        self.assertEqual(result["record"].category, "correction")

    def test_salary_keyword_sets_category(self):
        result = self.importer.detect_and_create_financial_record(
            self.txn_date,
            Decimal("-2000.00"),
            "Owner draw payroll",
            payer_account=PRIVATE_ACCOUNT,
        )
        self.assertEqual(result["record"].category, "salary")

    def test_keyword_fallback_without_private_account(self):
        # No private account configured → keyword-only fallback
        practice_no_private = _make_practice(slug="no-private-account")
        importer = _make_importer(practice_no_private, [])
        result = importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-2000.00"), "Owner draw Jan 2026"
        )
        self.assertEqual(result["type"], "CompanyWithdrawal")

    def test_unrelated_expense_creates_expense(self):
        practice_no_private = _make_practice(slug="expense-test")
        importer = _make_importer(practice_no_private, [])
        result = importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-120.00"), "Office rent"
        )
        self.assertEqual(result["type"], "CompanyExpense")
        self.assertEqual(CompanyExpense.objects.filter(practice=practice_no_private).count(), 1)

    def test_idempotent_duplicate(self):
        r1 = self.importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-300.00"), "Owner draw", payer_account=PRIVATE_ACCOUNT
        )
        r2 = self.importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-300.00"), "Owner draw", payer_account=PRIVATE_ACCOUNT
        )
        self.assertEqual(r1["record"].id, r2["record"].id)
        self.assertEqual(CompanyWithdrawal.objects.filter(practice=self.practice).count(), 1)

    def test_expense_uses_learned_rule_by_account(self):
        practice_no_private = _make_practice(slug="learned-rule-account")
        landlord_account = "ACH-LANDLORD-001"
        ExpenseCategoryRule.objects.create(
            practice=practice_no_private,
            match_key=build_counterparty_key(landlord_account, ""),
            category="rent",
        )
        importer = _make_importer(practice_no_private, [])
        result = importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-800.00"), "Rent August", payer_account=landlord_account
        )
        self.assertEqual(result["record"].category, "rent")

    def test_expense_uses_learned_rule_by_name_fallback(self):
        practice_no_private = _make_practice(slug="learned-rule-name")
        ExpenseCategoryRule.objects.create(
            practice=practice_no_private,
            match_key=build_counterparty_key("", "Telekom Deutschland"),
            category="phone_internet",
        )
        importer = _make_importer(practice_no_private, [])
        result = importer.detect_and_create_financial_record(
            self.txn_date,
            Decimal("-40.00"),
            "Invoice",
            payer_name="Telekom Deutschland",
        )
        self.assertEqual(result["record"].category, "phone_internet")

    def test_no_rule_still_defaults_to_other(self):
        practice_no_private = _make_practice(slug="no-learned-rule")
        importer = _make_importer(practice_no_private, [])
        result = importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-40.00"), "Unknown", payer_name="Irgendwer GmbH"
        )
        self.assertEqual(result["record"].category, "other")

    def test_rule_from_other_practice_is_ignored(self):
        landlord_account = "ACH-LANDLORD-001"
        other_practice = _make_practice(slug="other-practice-rule")
        ExpenseCategoryRule.objects.create(
            practice=other_practice,
            match_key=build_counterparty_key(landlord_account, ""),
            category="rent",
        )
        practice_no_private = _make_practice(slug="my-practice-no-rule")
        importer = _make_importer(practice_no_private, [])
        result = importer.detect_and_create_financial_record(
            self.txn_date, Decimal("-800.00"), "Rent August", payer_account=landlord_account
        )
        self.assertEqual(result["record"].category, "other")


class BuildCounterpartyKeyTest(TestCase):
    def test_account_takes_priority(self):
        key = build_counterparty_key("chk 4321", "Some Name")
        self.assertEqual(key, "account:CHK4321")

    def test_falls_back_to_normalized_name(self):
        key = build_counterparty_key("", "  Max Mustermann  ")
        self.assertEqual(key, "name:max mustermann")

    def test_blank_inputs_return_none(self):
        self.assertIsNone(build_counterparty_key("", ""))


# ── process (end-to-end CSV) ──────────────────────────────────────────────────


class ProcessCSVTest(TestCase):
    def setUp(self):
        self.practice = _make_practice(slug="process-csv")
        self.client_obj = Client.objects.create(
            practice=self.practice, full_name="Max Mustermann", client_code="MM"
        )
        self.invoice = Invoice.objects.create(
            practice=self.practice,
            client=self.client_obj,
            invoice_number="MM-1",
            status="sent",
            invoice_date=date(2026, 1, 1),
        )
        _make_invoice_item(self.invoice, self.practice, self.client_obj)

    def test_matched_invoice_marks_paid(self):
        importer = _make_importer(
            self.practice,
            [
                {"date": "01/15/2026", "payer": "Max Mustermann", "amount": "90.00", "ref": "MM-1"},
            ],
        )
        results = importer.process(skip_negatives=False)
        self.assertEqual(results["matched"], 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")

    def test_unmatched_transaction(self):
        importer = _make_importer(
            self.practice,
            [
                {
                    "date": "01/15/2026",
                    "payer": "Unknown",
                    "amount": "50.00",
                    "ref": "Transfer",
                },
            ],
        )
        results = importer.process(skip_negatives=False)
        self.assertEqual(results["unmatched"], 1)
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_duplicate_row_ignored(self):
        importer = _make_importer(
            self.practice,
            [
                {"date": "01/15/2026", "payer": "Somebody", "amount": "50.00", "ref": "Test Ref"},
                {"date": "01/15/2026", "payer": "Somebody", "amount": "50.00", "ref": "Test Ref"},
            ],
        )
        results = importer.process(skip_negatives=False)
        self.assertEqual(results["total"], 2)
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_negative_skipped_when_not_withdrawal(self):
        # No private account → no withdrawal detection → auto-expense is created regardless
        # but skip_negatives=True should still ignore unknown negatives after auto-create fails
        importer = _make_importer(
            self.practice,
            [
                {"date": "01/15/2026", "payer": "Landlord", "amount": "-500.00", "ref": "Rent"},
            ],
        )
        results = importer.process(skip_negatives=True)
        # With no private IBAN, "Rent" has no keyword match → CompanyExpense created,
        # transaction recorded with auto-expense confidence
        self.assertEqual(results["needs_review"], 1)

    def test_negative_not_skipped_when_skip_negatives_false(self):
        importer = _make_importer(
            self.practice,
            [
                {"date": "01/15/2026", "payer": "Landlord", "amount": "-500.00", "ref": "Rent"},
            ],
        )
        results = importer.process(skip_negatives=False)
        self.assertEqual(results["needs_review"], 1)


class ConfigurableCsvFormatTest(TestCase):
    """A non-default delimiter/column mapping (issue #11) should parse and match correctly."""

    def setUp(self):
        self.practice = _make_practice(
            slug="custom-csv-format",
            csv_delimiter="|",
            csv_column_date="TxnDate",
            csv_column_value_date="",
            csv_column_payer_name="Description",
            csv_column_payer_account="",
            csv_column_reference="Description",
            csv_column_amount="Amt",
            csv_column_balance="",
            csv_column_account="",
        )
        self.client_obj = Client.objects.create(
            practice=self.practice, full_name="Max Mustermann", client_code="MM"
        )
        self.invoice = Invoice.objects.create(
            practice=self.practice,
            client=self.client_obj,
            invoice_number="MM-1",
            status="sent",
            invoice_date=date(2026, 1, 1),
        )
        _make_invoice_item(self.invoice, self.practice, self.client_obj)

    def _make_custom_importer(self, rows):
        """Minimal export: date, description and amount only — the optional columns are absent."""
        lines = ["TxnDate|Description|Amt"]
        lines.extend(f"{r['date']}|{r['ref']}|{r['amount']}" for r in rows)
        content = "\n".join(lines).encode("utf-8")
        csv_file = SimpleUploadedFile("test.csv", content, content_type="text/csv")
        return BankStatementImporter(csv_file, self.practice)

    def test_optional_columns_default_sensibly(self):
        importer = self._make_custom_importer(
            [{"date": "2026-01-15", "amount": "1,250.00", "ref": "Deposit"}]
        )
        importer.process(skip_negatives=False)
        transaction = BankTransaction.objects.get()
        self.assertEqual(transaction.value_date, date(2026, 1, 15))
        self.assertIsNone(transaction.balance_after)
        self.assertEqual(transaction.amount, Decimal("1250.00"))

    def test_matches_invoice_with_custom_delimiter_and_columns(self):
        importer = self._make_custom_importer(
            [{"date": "01/15/2026", "amount": "90.00", "ref": "Zelle from Max Mustermann MM-1"}]
        )
        results = importer.process(skip_negatives=False)
        self.assertEqual(results["matched"], 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")


class IngestTransactionTest(TestCase):
    """
    The source-agnostic half of the importer, driven without any CSV.

    These exercise the seam a bank-API fetcher would use: build the importer
    with for_account(), hand it normalized dicts, and get the same matching,
    duplicate suppression and invoice bookkeeping the CSV path gets.
    """

    def setUp(self):
        self.practice = _make_practice(slug="ingest-tx")
        self.client_obj = Client.objects.create(
            practice=self.practice, full_name="Anna Schmidt", client_code="AS"
        )
        self.invoice = Invoice.objects.create(
            practice=self.practice,
            client=self.client_obj,
            invoice_number="AS-1",
            status="sent",
            invoice_date=date(2026, 1, 1),
        )
        _make_invoice_item(self.invoice, self.practice, self.client_obj)

    def _parsed(self, **overrides):
        """Build a normalized transaction dict, as a non-CSV fetcher would."""
        parsed = {
            "transaction_date": date(2026, 1, 15),
            "value_date": date(2026, 1, 15),
            "payer_name": "Anna Schmidt",
            "payer_account": "",
            "reference": "AS-1",
            "amount": Decimal("90.00"),
            "balance_after": Decimal("1000.00"),
        }
        parsed.update(overrides)
        return parsed

    def test_for_account_sets_normalized_account(self):
        importer = BankStatementImporter.for_account(self.practice, "chk 4321")
        self.assertEqual(importer.source_account, PRACTICE_ACCOUNT)

    def test_external_id_deduplicates(self):
        """A bank-connection transaction ID wins over date/amount/memo matching."""
        importer = BankStatementImporter.for_account(self.practice, PRACTICE_ACCOUNT)
        importer.ingest_transaction(self._parsed(external_id="txn-1"), skip_negatives=False)
        second = importer.ingest_transaction(
            self._parsed(external_id="txn-1", reference="AS-1 (edited memo)"),
            skip_negatives=False,
        )
        self.assertIsNone(second)
        self.assertEqual(BankTransaction.objects.get().external_id, "txn-1")

    def test_ingest_matches_invoice_without_csv(self):
        importer = BankStatementImporter.for_account(self.practice, PRACTICE_ACCOUNT)
        transaction = importer.ingest_transaction(self._parsed(), skip_negatives=False)

        self.assertIsNotNone(transaction)
        self.assertEqual(importer.results["total"], 1)
        self.assertEqual(importer.results["matched"], 1)
        self.assertEqual(transaction.source_account, PRACTICE_ACCOUNT)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        self.assertEqual(self.invoice.paid_date, date(2026, 1, 15))

    def test_ingest_suppresses_duplicate(self):
        importer = BankStatementImporter.for_account(self.practice, PRACTICE_ACCOUNT)
        importer.ingest_transaction(self._parsed(), skip_negatives=False)
        second = importer.ingest_transaction(self._parsed(), skip_negatives=False)

        self.assertIsNone(second)
        self.assertEqual(importer.results["total"], 2)
        self.assertEqual(importer.results["ignored"], 1)
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_ingest_routes_negative_to_expense(self):
        """Negatives take the same auto-expense path they take from CSV."""
        importer = BankStatementImporter.for_account(self.practice, PRACTICE_ACCOUNT)
        transaction = importer.ingest_transaction(
            self._parsed(amount=Decimal("-40.00"), reference="Rent"), skip_negatives=True
        )

        # _handle_negative_row owns the row, so ingest_transaction returns None
        # even though a BankTransaction and a CompanyExpense were created.
        self.assertIsNone(transaction)
        self.assertEqual(importer.results["total"], 1)
        self.assertEqual(importer.results["needs_review"], 1)
        self.assertEqual(CompanyExpense.objects.count(), 1)
        self.assertEqual(BankTransaction.objects.get().source_account, PRACTICE_ACCOUNT)

    def test_csv_and_ingest_agree(self):
        """The CSV path and a hand-built dict produce the same stored row."""
        csv_importer = _make_importer(
            self.practice,
            [{"date": "01/15/2026", "payer": "Anna Schmidt", "amount": "90.00", "ref": "AS-1"}],
        )
        csv_importer.process(skip_negatives=False)
        via_csv = BankTransaction.objects.get()

        self.invoice.status = "sent"
        self.invoice.paid_date = None
        self.invoice.save()
        via_csv.delete()

        api_importer = BankStatementImporter.for_account(self.practice, PRACTICE_ACCOUNT)
        via_api = api_importer.ingest_transaction(self._parsed(), skip_negatives=False)

        for field in (
            "transaction_date",
            "value_date",
            "payer_name",
            "reference",
            "amount",
            "balance_after",
            "source_account",
            "match_confidence",
            "extracted_invoice_number",
        ):
            self.assertEqual(getattr(via_csv, field), getattr(via_api, field), f"{field} differs")
        self.assertEqual(via_csv.matched_invoice_id, via_api.matched_invoice_id)
