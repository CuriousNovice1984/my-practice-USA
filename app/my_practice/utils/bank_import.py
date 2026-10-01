"""
Bank statement import and matching utilities.

Handles CSV parsing, invoice number extraction, and automatic payment matching.
Transactions from a bank connection (Plaid) go through the same matching via
``BankStatementImporter.for_account()`` + ``ingest_transaction()``.
"""

import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from ..models import (
    BankTransaction,
    ClientAlias,
    CompanyExpense,
    CompanyWithdrawal,
    ExpenseCategoryRule,
    Invoice,
)


class BankStatementImporter:
    """
    Import and match bank transactions from CSV files.

    The delimiter and column headers are read from the practice's
    csv_delimiter/csv_column_* settings (Practice model), so any bank's
    export can be supported without touching code.

    Format details:
    - Encoding: UTF-8 (a leading byte-order mark is tolerated)
    - Delimiter: configurable, default comma
    - Amounts: US format — "1,234.56", "-1,234.56", "(1,234.56)", "$1,234.56"
    - Dates: MM/DD/YYYY, MM/DD/YY or YYYY-MM-DD

    Usage:
        importer = BankStatementImporter(csv_file, practice)
        results = importer.process()
    """

    # Invoice number extraction patterns (priority order)
    INVOICE_PATTERNS = [
        # Pattern 1: Direct codes (XX-1, YY-2, AB-3)
        r"\b([A-Z]{2,4}-\d+)\b",
        # Pattern 2: with a keyword prefix before the code ("Invoice No. XX-1", "Inv #XX-1")
        r"(?:Invoice|Inv)\s*(?:No\.?|#)?\s*([A-Z]{2,4}-\d+)",
    ]

    # Keywords for owner-pay withdrawal detection
    WITHDRAWAL_KEYWORDS = [
        "owner draw",
        "owner's draw",
        "owners draw",
        "payroll",
    ]

    # Keywords for correction / reversal detection
    CORRECTION_KEYWORDS = [
        "reversal",
        "correction",
        "adjustment",
    ]

    @staticmethod
    def _normalize_account(account: str) -> str:
        """Normalize an account identifier by removing spaces and uppercasing."""
        return account.replace(" ", "").upper()

    @classmethod
    def for_account(cls, practice, source_account: str) -> "BankStatementImporter":
        """
        Build an importer for a non-CSV source (e.g. a bank API fetcher).

        ``process()`` is unavailable on the result — there is no file to read
        and no CSV header to validate the account against — so the caller is
        responsible for producing normalized dicts and feeding them to
        ``ingest_transaction()`` itself. The account identifier is supplied up
        front because it would otherwise be read from the CSV.

        Args:
            practice: Practice instance for scoping
            source_account: Identifier of the account the transactions belong to

        Returns:
            An importer with only the source-agnostic half wired up.
        """
        importer = cls(None, practice)
        importer.source_account = cls._normalize_account(source_account)
        return importer

    def __init__(self, csv_file, practice):
        """
        Initialize importer.

        Args:
            csv_file: File object with CSV content, or None when the
                transactions come from somewhere other than a CSV upload
                (see ``for_account()``)
            practice: Practice instance for scoping
        """
        self.csv_file = csv_file
        self.practice = practice
        # Normalized private account identifier for withdrawal/contribution detection
        self.private_account = (
            self._normalize_account(practice.private_bank_account)
            if practice.private_bank_account
            else ""
        )
        # Source account from the CSV (populated during process())
        self.source_account: str = ""
        self.results: dict[str, Any] = {
            "total": 0,
            "matched": 0,
            "unmatched": 0,
            "needs_review": 0,
            "ignored": 0,
            "errors": [],
            "transactions": [],
        }

    def parse_amount(self, value: str) -> Decimal:
        """
        Parse a US-format amount to Decimal.

        Args:
            value: String like "90.00", "-1,234.56", "(300.00)" or "$1,234.56"

        Returns:
            Decimal object (parenthesized amounts are negative)

        Raises:
            InvalidOperation: If parsing fails
        """
        text = value.strip().replace("$", "").replace(",", "").replace(" ", "")
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        return Decimal(text)

    DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")

    def parse_date(self, value: str) -> "date":
        """
        Parse a bank-export date.

        Args:
            value: String like "02/14/2026", "02/14/26" or "2026-02-14"

        Returns:
            datetime.date object

        Raises:
            ValueError: If no supported format matches
        """
        text = value.strip()
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unrecognized date: {value!r}")

    def extract_invoice_number(self, reference: str) -> str | None:
        """
        Extract invoice number from reference text using regex patterns.

        Args:
            reference: Payment memo/description text

        Returns:
            Extracted invoice number (uppercase) or None

        Examples:
            "XX-1" → "XX-1"
            "Invoice No. YY-2" → "YY-2"
            "Zelle payment from M Schmidt for CD-4" → "CD-4"
            "Wed 9-10" → None
        """
        for pattern in self.INVOICE_PATTERNS:
            match = re.search(pattern, reference, re.IGNORECASE)
            if match:
                # Extract captured group and normalize to uppercase
                invoice_number = match.group(1).upper()
                return invoice_number
        return None

    def find_matching_invoice(
        self, invoice_number: str, amount: Decimal, payer_name: str
    ) -> tuple[Invoice, str] | None:
        """
        Find invoice matching the extracted number and amount exactly.

        Uses fuzzy name matching via ClientAlias for name variations
        (parent payments, legal name changes, bank account differences).

        Args:
            invoice_number: Extracted invoice number
            amount: Transaction amount (must match exactly)
            payer_name: Name from bank statement

        Returns:
            Tuple of (Invoice, confidence) or None
            Confidence values: "exact" (direct match), "fuzzy" (via alias)
        """
        try:
            # Find invoice by number with exact amount
            invoice = Invoice.objects.filter(
                practice=self.practice,
                invoice_number=invoice_number,
                status="sent",  # Only match unpaid invoices
            ).first()

            if not invoice:
                return None

            # Calculate invoice total
            invoice_total = invoice.calculate_total()

            # Require exact amount match (no tolerance)
            if abs(invoice_total - amount) >= Decimal("0.01"):
                return None

            # Direct match
            if invoice.client.full_name.lower() == payer_name.lower():
                return (invoice, "exact")

            # Fuzzy match via ClientAlias
            alias = ClientAlias.objects.filter(
                client=invoice.client, alias_name__iexact=payer_name
            ).first()

            if alias:
                return (invoice, "fuzzy")

            # Amount matches but name doesn't - still return as exact
            # (user can create alias if needed)
            return (invoice, "exact")

        except Invoice.MultipleObjectsReturned:
            # Should not happen with unique invoice_number
            return None

    def detect_and_create_financial_record(
        self, transaction_date, amount, reference, payer_account: str = "", payer_name: str = ""
    ) -> dict | None:
        """
        Detect if a negative transaction is a withdrawal or expense and create it.

        Detection priority and category assignment:
        - Private account match + correction keywords → CompanyWithdrawal(correction)
        - Private account match + owner-draw keywords → CompanyWithdrawal(salary)
        - Private account match, no keywords          → CompanyWithdrawal(private_transfer)
        - No private account configured, correction keywords → CompanyWithdrawal(correction)
        - No private account configured, owner-draw keywords → CompanyWithdrawal(salary)
        - Otherwise → CompanyExpense, category from a learned ExpenseCategoryRule
          for this counterparty if one exists, else "other"

        Args:
            transaction_date: Date of transaction
            amount: Transaction amount (negative)
            reference: Transaction reference text
            payer_account: Account identifier of the counterparty, if the source provides one
            payer_name: Name of the counterparty, used as a fallback categorization key

        Returns:
            Dictionary with type and created record, or None if not auto-created
        """
        reference_lower = reference.lower()
        abs_amount = abs(amount)

        # Private-account detection: if the private account is configured and the
        # transaction goes to/from it (via payer_account field OR mention in the memo,
        # e.g. "Online transfer to CHK ...1234"), it's a private-account transaction.
        private_account_match = bool(
            self.private_account
            and (
                self._normalize_account(payer_account) == self.private_account
                or self.private_account in self._normalize_account(reference)
            )
        )

        # Keyword sub-classification — used to assign category regardless of how
        # the withdrawal was detected (private account or fallback).
        salary_keyword_hit = any(keyword in reference_lower for keyword in self.WITHDRAWAL_KEYWORDS)
        correction_keyword_hit = any(
            keyword in reference_lower for keyword in self.CORRECTION_KEYWORDS
        )

        # Keyword fallback: only fires when no private account is configured, to avoid
        # false positives on client payments that mention payroll-related words.
        keyword_match = not self.private_account and (salary_keyword_hit or correction_keyword_hit)

        is_withdrawal = private_account_match or keyword_match

        if is_withdrawal:
            # Check if withdrawal already exists
            existing_withdrawal = CompanyWithdrawal.objects.filter(
                practice=self.practice,
                date=transaction_date,
                amount=abs_amount,
                description=reference,
            ).first()

            if existing_withdrawal:
                return {"type": "CompanyWithdrawal", "record": existing_withdrawal}

            # Category priority:
            # 1. Correction keywords (reversal/correction) → correction
            # 2. Owner-draw keywords (owner draw/payroll) → salary
            # 3. Private account match only (plain transfer, no keywords) → private_transfer
            if correction_keyword_hit:
                withdrawal_category = "correction"
            elif salary_keyword_hit:
                withdrawal_category = "salary"
            else:
                withdrawal_category = "private_transfer"
            withdrawal = CompanyWithdrawal.objects.create(
                practice=self.practice,
                date=transaction_date,
                amount=abs_amount,
                description=reference,
                category=withdrawal_category,
            )
            return {"type": "CompanyWithdrawal", "record": withdrawal}
        else:
            # Check if expense already exists
            existing_expense = CompanyExpense.objects.filter(
                practice=self.practice,
                date=transaction_date,
                amount=abs_amount,
                description=reference,
            ).first()

            if existing_expense:
                return {"type": "CompanyExpense", "record": existing_expense}

            # Create CompanyExpense for other negative amounts, using a learned
            # category for this counterparty when one is on file.
            match_key = build_counterparty_key(payer_account, payer_name)
            rule = (
                ExpenseCategoryRule.objects.filter(
                    practice=self.practice, match_key=match_key
                ).first()
                if match_key
                else None
            )
            expense = CompanyExpense.objects.create(
                practice=self.practice,
                date=transaction_date,
                amount=abs_amount,
                description=reference,
                category=rule.category if rule else "other",
                has_invoice=False,
                is_tax_deductible=True,
            )
            return {"type": "CompanyExpense", "record": expense}

    def parse_csv_row(self, row: dict[str, str]) -> dict | None:
        """
        Parse a single CSV row into transaction data.

        Args:
            row: Dictionary with CSV column headers as keys

        Returns:
            Dictionary with parsed transaction data or None if parsing fails
        """
        practice = self.practice

        def optional(column: str) -> str:
            return row.get(column, "").strip() if column else ""

        try:
            transaction_date = self.parse_date(row[practice.csv_column_date])
            value_date_raw = optional(practice.csv_column_value_date)
            balance_raw = optional(practice.csv_column_balance)
            return {
                "transaction_date": transaction_date,
                "value_date": self.parse_date(value_date_raw)
                if value_date_raw
                else transaction_date,
                "payer_name": row[practice.csv_column_payer_name].strip(),
                "payer_account": optional(practice.csv_column_payer_account),
                "reference": row[practice.csv_column_reference].strip(),
                "amount": self.parse_amount(row[practice.csv_column_amount]),
                "balance_after": self.parse_amount(balance_raw) if balance_raw else None,
            }
        except KeyError, ValueError, InvalidOperation:
            return None

    def _validate_columns(self, header: list[str]) -> bool:
        """Check the CSV has every required column. Sets an error and returns False if not."""
        practice = self.practice
        required = {
            practice.csv_column_date,
            practice.csv_column_payer_name,
            practice.csv_column_reference,
            practice.csv_column_amount,
        }
        missing = sorted(required - {h.strip() for h in header})
        if missing:
            self.results["errors"].append(
                _(
                    "The CSV file is missing the column(s) %(missing)s. Check the column "
                    "names in the practice settings (Bank Import) against your bank's export."
                )
                % {"missing": ", ".join(f'"{m}"' for m in missing)}
            )
            self.results["invalid_format"] = True
            return False
        return True

    def _find_existing(self, parsed: dict) -> "BankTransaction | None":
        """Return the already-imported transaction for this row, if any.

        A bank-connection transaction ID is authoritative when present; otherwise
        (CSV) the date + amount + memo triple identifies a transaction.
        """
        qs = BankTransaction.objects.for_practice(self.practice)
        external_id = parsed.get("external_id", "")
        if external_id:
            existing = qs.filter(external_id=external_id).first()
            if existing:
                return existing
        return qs.filter(
            transaction_date=parsed["transaction_date"],
            amount=parsed["amount"],
            reference=parsed["reference"],
        ).first()

    def _handle_negative_row(self, parsed: dict, skip_negatives: bool) -> bool:
        """Handle a negative-amount row. Returns True if fully processed (caller should continue)."""
        existing = self._find_existing(parsed)
        if existing:
            self.results["ignored"] += 1
            return True

        withdrawal_or_expense = self.detect_and_create_financial_record(
            parsed["transaction_date"],
            parsed["amount"],
            parsed["reference"],
            payer_account=parsed["payer_account"],
            payer_name=parsed["payer_name"],
        )
        if withdrawal_or_expense:
            record_type = withdrawal_or_expense["type"]
            record = withdrawal_or_expense["record"]
            if record_type == "CompanyWithdrawal":
                match_confidence, linked_expense, linked_withdrawal = (
                    "auto-withdrawal",
                    None,
                    record,
                )
            else:
                match_confidence, linked_expense, linked_withdrawal = "auto-expense", record, None
            BankTransaction.objects.create(
                practice=self.practice,
                transaction_date=parsed["transaction_date"],
                value_date=parsed["value_date"],
                payer_name=parsed["payer_name"],
                payer_account=parsed["payer_account"],
                reference=parsed["reference"],
                amount=parsed["amount"],
                balance_after=parsed["balance_after"],
                source_account=self.source_account,
                external_id=parsed.get("external_id", ""),
                match_confidence=match_confidence,
                linked_expense=linked_expense,
                linked_withdrawal=linked_withdrawal,
                notes=f"Auto-created {record_type}: {record}",
                processed=record_type == "CompanyWithdrawal",
            )
            self.results["needs_review"] += 1
            return True

        if skip_negatives:
            self.results["ignored"] += 1
            return True

        return False

    def _classify_transaction(
        self,
        parsed: dict,
        is_private_contribution: bool,
        is_self_payment: bool,
        invoice_number: str | None,
    ) -> tuple[str, str, Invoice | None, CompanyWithdrawal | None]:
        """Classify a transaction and update result counters. Returns (confidence, notes, matched_invoice, linked_withdrawal)."""
        confidence = "unmatched"
        notes = ""
        linked_withdrawal = None
        matched_invoice = None

        if is_private_contribution:
            reference_lower = parsed["reference"].lower()
            correction_keyword_hit = any(kw in reference_lower for kw in self.CORRECTION_KEYWORDS)
            # Positive transactions from the private account with a correction keyword
            # (e.g. "reversal") are bank errors, not real contributions.
            if correction_keyword_hit:
                withdrawal_category = "correction"
                confidence = "auto-correction"
                notes = "Correction from private account"
            else:
                withdrawal_category = "contribution"
                confidence = "auto-contribution"
                notes = "Owner contribution from private account"
            # Only create for positive (incoming) amounts
            if parsed["amount"] > 0:
                withdrawal, _ = CompanyWithdrawal.objects.get_or_create(
                    practice=self.practice,
                    date=parsed["transaction_date"],
                    amount=parsed["amount"],
                    description=parsed["reference"],
                    defaults={"category": withdrawal_category},
                )
                linked_withdrawal = withdrawal
            self.results["needs_review"] += 1
        elif is_self_payment:
            confidence = "ignored"
            notes = "Own payment (contribution) - ignored automatically"
            self.results["ignored"] += 1
        elif invoice_number:
            match_result = self.find_matching_invoice(
                invoice_number, parsed["amount"], parsed["payer_name"]
            )
            if match_result:
                matched_invoice, confidence = match_result
                self.results["matched"] += 1
            else:
                self.results["unmatched"] += 1
        else:
            self.results["unmatched"] += 1

        return confidence, notes, matched_invoice, linked_withdrawal

    @transaction.atomic
    def process(self, skip_negatives: bool = True) -> dict[str, Any]:
        """
        Process CSV file and match transactions to invoices.

        Args:
            skip_negatives: If True, ignore negative amounts (expenses)

        Returns:
            Dictionary with processing results
        """
        content = self.csv_file.read().decode("utf-8-sig")
        reader = csv.DictReader(content.splitlines(), delimiter=self.practice.csv_delimiter)
        if not self._validate_columns(reader.fieldnames or []):
            return self.results
        rows = list(reader)
        if rows and self.practice.csv_column_account:
            self.source_account = rows[0].get(self.practice.csv_column_account, "").strip()

        for row in rows:
            parsed = self.parse_csv_row(row)
            if not parsed:
                self.results["total"] += 1
                self.results["errors"].append(_("Failed to parse row: %(row)s") % {"row": row})
                continue

            self.ingest_transaction(parsed, skip_negatives=skip_negatives)

        return self.results

    def ingest_transaction(
        self, parsed: dict[str, Any], skip_negatives: bool = True
    ) -> "BankTransaction | None":
        """
        Classify one already-parsed transaction and record it.

        This is the source-agnostic half of the import: everything from the
        duplicate check onwards depends only on the normalized dict, never on
        where it came from. ``process()`` feeds it rows parsed from CSV; a
        fetcher for a bank API can build the same dict and call this directly
        (see ``for_account()``).

        Args:
            parsed: Normalized transaction dict with the keys produced by
                ``parse_csv_row``: transaction_date, value_date, payer_name,
                payer_account, reference, amount, balance_after — plus an
                optional ``external_id`` from a bank connection
            skip_negatives: If True, ignore negative amounts (expenses)

        Returns:
            The created BankTransaction, or None if the row was ignored as a
            duplicate or handled as a negative/expense row.
        """
        self.results["total"] += 1

        payer_name_lower = parsed["payer_name"].lower().strip()
        is_self_payment = payer_name_lower == self.practice.name.lower().strip()

        # Private-account contribution detection takes priority over name matching.
        # Check both the payer_account field AND the memo text (banks embed account hints there).
        payer_account_normalized = self._normalize_account(parsed["payer_account"])
        reference_normalized = self._normalize_account(parsed["reference"])
        is_private_contribution = bool(
            self.private_account
            and (
                payer_account_normalized == self.private_account
                or self.private_account in reference_normalized
            )
        )

        if parsed["amount"] < 0 and self._handle_negative_row(parsed, skip_negatives):
            return None

        # Duplicate check for non-negative (and unhandled negative) rows
        existing = self._find_existing(parsed)
        if existing:
            self.results["ignored"] += 1
            return None

        invoice_number = self.extract_invoice_number(parsed["reference"])
        confidence, notes, matched_invoice, linked_withdrawal = self._classify_transaction(
            parsed, is_private_contribution, is_self_payment, invoice_number
        )

        bank_transaction = BankTransaction.objects.create(
            practice=self.practice,
            transaction_date=parsed["transaction_date"],
            value_date=parsed["value_date"],
            payer_name=parsed["payer_name"],
            payer_account=parsed["payer_account"],
            reference=parsed["reference"],
            amount=parsed["amount"],
            balance_after=parsed["balance_after"],
            source_account=self.source_account,
            external_id=parsed.get("external_id", ""),
            matched_invoice=matched_invoice,
            match_confidence=confidence,
            extracted_invoice_number=invoice_number or "",
            linked_withdrawal=linked_withdrawal,
            notes=notes,
            processed=matched_invoice is not None,
        )

        if matched_invoice:
            matched_invoice.status = "paid"
            matched_invoice.paid_date = parsed["transaction_date"]
            matched_invoice.save()

        self.results["transactions"].append(bank_transaction)
        return bank_transaction


def build_counterparty_key(payer_account: str, payer_name: str) -> str | None:
    """
    Build the ExpenseCategoryRule.match_key for a bank counterparty.

    The counterparty account is preferred when present (more reliable than
    free-text names on statements); falls back to the normalized payer name.
    Returns None when neither is available.
    """
    normalized_account = (
        BankStatementImporter._normalize_account(payer_account) if payer_account else ""
    )
    if normalized_account:
        return f"account:{normalized_account}"
    normalized_name = payer_name.strip().lower()
    return f"name:{normalized_name}" if normalized_name else None
