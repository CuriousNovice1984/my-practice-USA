"""
Tests for the email content builders in utils/email_utils.py.

These build the subject and body text that actually reaches a client.
test_email_views.py mocks the send, so it asserts that an email went out but
never what it said — the assertions on content live here.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from my_practice.models import (
    Client,
    Invoice,
    InvoiceItem,
    Practice,
    ServiceType,
    Session,
    TimeOff,
)
from my_practice.utils.email_utils import (
    get_invoice_email_content,
    get_questionnaire_pdf_email_content,
    get_records_deletion_email_content,
    get_salutation_for_client,
    get_timeoff_notice_default_content,
    prepare_invoice_email_context,
    render_email_template,
)
from my_practice.utils.formatting import format_currency
from my_practice.validators import validate_email_template_placeholders


class FormatCurrencyTest(TestCase):
    """format_currency is the single definition of how money is written."""

    def test_us_separators(self):
        self.assertEqual(format_currency(Decimal("11064.03")), "$11,064.03")

    def test_negative_sign_precedes_symbol(self):
        self.assertEqual(format_currency(Decimal("-5")), "-$5.00")

    def test_always_two_decimals(self):
        self.assertEqual(format_currency(Decimal("100")), "$100.00")

    def test_matches_the_currency_template_filter(self):
        """The email and the |currency filter used by the PDF must agree."""
        from my_practice.templatetags.payment_tags import currency

        for value in (Decimal("0.99"), Decimal("1234.50"), Decimal("11064.03")):
            self.assertEqual(currency(value), format_currency(value))


class RenderEmailTemplateTest(TestCase):
    """Rendering is total: free text typed by the practitioner must never crash a send."""

    def test_substitutes_known_placeholders(self):
        self.assertEqual(
            render_email_template("Hallo {salutation}!", {"salutation": "Liebe:r Max"}),
            "Hallo Liebe:r Max!",
        )

    def test_unknown_placeholder_left_standing_instead_of_raising(self):
        # Previously str.format() raised KeyError and aborted the send.
        self.assertEqual(
            render_email_template("Betrag: {Betrag}", {"amount": "5"}), "Betrag: {Betrag}"
        )

    def test_stray_opening_brace_does_not_raise(self):
        # e.g. the practitioner typing a brace in ordinary prose.
        self.assertEqual(render_email_template("costs { or so", {}), "costs { or so")

    def test_unmatched_closing_brace_does_not_raise(self):
        self.assertEqual(render_email_template("50%} off", {}), "50%} off")

    def test_attribute_traversal_is_not_a_placeholder(self):
        """{obj.__class__} was reachable under str.format; now it is literal text."""
        out = render_email_template("{client.__class__}", {"client": object()})
        self.assertEqual(out, "{client.__class__}")

    def test_repeated_placeholder_substituted_everywhere(self):
        self.assertEqual(render_email_template("{a}-{a}", {"a": "x"}), "x-x")

    def test_non_string_context_values_are_coerced(self):
        self.assertEqual(render_email_template("n={n}", {"n": 3}), "n=3")


class ValidateEmailTemplatePlaceholdersTest(TestCase):
    """Save-time validation is what surfaces a typo while it can still be fixed."""

    def test_accepts_every_supported_placeholder(self):
        text = "{salutation} {sessions_intro} {invoice_number} {amount} {date} {client_name}"
        validate_email_template_placeholders(text)  # must not raise

    def test_accepts_text_without_placeholders(self):
        validate_email_template_placeholders("Plain text, no placeholders.")

    def test_rejects_unknown_placeholder(self):
        with self.assertRaises(ValidationError):
            validate_email_template_placeholders("Betrag: {Betrag}")

    def test_error_names_the_offending_placeholder(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_email_template_placeholders("{Betrag} and {Datum}")
        message = str(ctx.exception)
        self.assertIn("{Betrag}", message)
        self.assertIn("{Datum}", message)

    def test_stray_brace_is_not_treated_as_a_placeholder(self):
        validate_email_template_placeholders("a { b } c")  # must not raise

    def test_empty_value_accepted(self):
        validate_email_template_placeholders("")

    def test_enforced_by_the_admin_form(self):
        """The admin is the only edit path for these fields — check it really rejects."""
        from django.contrib import admin as django_admin

        from my_practice.models import Practice

        model_admin = django_admin.site._registry[Practice]
        form_class = model_admin.get_form(request=None)

        practice = Practice(name="Test Practice", slug="validator-admin-check")
        form = form_class(
            instance=practice,
            data={
                **{f: getattr(practice, f, "") or "" for f in form_class.base_fields},
                "name": "Test Practice",
                "slug": "validator-admin-check",
                "invoice_email_subject": "Invoice {invoice_number}",
                "invoice_email_body": "{salutation},\n\nAmount: {Betrag}",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("invoice_email_body", form.errors)
        self.assertIn("{Betrag}", str(form.errors["invoice_email_body"]))
        # ...and the correctly-spelled sibling field is not blamed
        self.assertNotIn("invoice_email_subject", form.errors)


class EmailContentBuilderTestBase(TestCase):
    """Shared fixtures: one practice, one client."""

    def setUp(self):
        self.practice = Practice.objects.create(
            name="Test Practice",
            slug="email-content-builders",
            title="Test Practitioner",
            email="practice@practice.example",
            city="Austin",
            email_signature="Best regards\nAnna Schmidt",
        )
        self.client_obj = Client.objects.create(
            client_code="CD-2",
            full_name="Jane Doe",
            email="jane@example.com",
            practice=self.practice,
        )


class SalutationTest(EmailContentBuilderTestBase):
    def test_fallback_uses_first_name(self):
        self.assertEqual(get_salutation_for_client(self.client_obj), "Dear Jane")

    def test_custom_salutation_overrides_fallback(self):
        self.client_obj.salutation = "Hi Jane"
        self.assertEqual(get_salutation_for_client(self.client_obj), "Hi Jane")

    def test_blank_full_name_falls_back_to_client(self):
        nameless = Client.objects.create(client_code="EF-3", full_name="", practice=self.practice)
        self.assertEqual(get_salutation_for_client(nameless), "Dear Client")


class InvoiceEmailContentTest(EmailContentBuilderTestBase):
    def _make_invoice(self, total="1234.50"):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            invoice_number="CD-2-1",
            status="draft",
            total=Decimal(total),
            practice=self.practice,
        )
        # Invoice.save() forces invoice_date to today when creating a draft,
        # so pin it afterwards to keep the rendered date assertion stable.
        invoice.invoice_date = date(2026, 8, 15)
        invoice.save(update_fields=["invoice_date"])
        return invoice

    def test_amount_format_matches_the_attached_pdf(self):
        context = prepare_invoice_email_context(self._make_invoice(), self.practice)
        self.assertEqual(context["amount"], "$1,234.50")

    def test_context_carries_every_documented_placeholder(self):
        context = prepare_invoice_email_context(self._make_invoice(), self.practice)
        self.assertEqual(context["invoice_number"], "CD-2-1")
        self.assertEqual(context["date"], "15 Aug 26")
        self.assertEqual(context["client_name"], "Jane Doe")
        self.assertEqual(context["salutation"], "Dear Jane")

    def test_custom_salutation_overrides_context(self):
        context = prepare_invoice_email_context(
            self._make_invoice(), self.practice, custom_salutation="Hey"
        )
        self.assertEqual(context["salutation"], "Hey")

    def test_default_template(self):
        subject, body = get_invoice_email_content(self._make_invoice(), self.practice)
        self.assertEqual(subject, "Invoice CD-2-1")
        self.assertIn("Please find attached invoice CD-2-1 for $1,234.50", body)

    def test_amount_rendered_into_body_not_left_as_placeholder(self):
        _, body = get_invoice_email_content(self._make_invoice(), self.practice)
        self.assertNotIn("{amount}", body)
        self.assertNotIn("{invoice_number}", body)
        self.assertNotIn("{salutation}", body)

    def test_signature_appended(self):
        _, body = get_invoice_email_content(self._make_invoice(), self.practice)
        self.assertTrue(body.endswith("-- \nBest regards\nAnna Schmidt"))

    def test_no_dangling_delimiter_when_signature_empty(self):
        """An empty signature must not leave a bare "-- " sig delimiter on the mail."""
        self.practice.email_signature = ""
        _, body = get_invoice_email_content(self._make_invoice(), self.practice)
        self.assertNotIn("-- \n", body)

    def test_custom_message_appended_before_signature(self):
        _, body = get_invoice_email_content(
            self._make_invoice(), self.practice, custom_message="See you soon!"
        )
        self.assertIn("See you soon!", body)
        self.assertLess(body.index("See you soon!"), body.index("Best regards"))

    def test_broken_template_renders_instead_of_crashing_the_send(self):
        """A template already stored with a typo must not abort the send."""
        self.practice.invoice_email_body = "{salutation},\n\nAmount: {Betrag}"
        _, body = get_invoice_email_content(self._make_invoice(), self.practice)
        self.assertIn("Dear Jane", body)
        self.assertIn("{Betrag}", body)


class SessionsIntroTest(EmailContentBuilderTestBase):
    """The opening sentence summarising which sessions an invoice covers."""

    def _invoice_with_sessions(self, session_dates):
        service_type = ServiceType.objects.create(
            practice=self.practice,
            code="INDIVIDUAL",
            name="Individual session",
        )
        invoice = Invoice.objects.create(
            client=self.client_obj,
            invoice_number="CD-2-9",
            status="draft",
            total=Decimal("100.00"),
            practice=self.practice,
        )
        for d in session_dates:
            session = Session.objects.create(client=self.client_obj, session_date=d, duration=60)
            InvoiceItem.objects.create(
                invoice=invoice,
                session=session,
                service_type=service_type,
                rate=Decimal("50.00"),
                quantity=Decimal("1"),
            )
        return invoice

    def test_single_month_singular(self):
        invoice = self._invoice_with_sessions([date(2026, 7, 3)])
        _, body = get_invoice_email_content(invoice, self.practice)
        self.assertIn("our session in July", body)

    def test_single_month_plural(self):
        invoice = self._invoice_with_sessions([date(2026, 7, 3), date(2026, 7, 10)])
        _, body = get_invoice_email_content(invoice, self.practice)
        self.assertIn("our sessions in July", body)

    def test_spanning_months_counts_sessions(self):
        invoice = self._invoice_with_sessions([date(2026, 6, 30), date(2026, 7, 1)])
        _, body = get_invoice_email_content(invoice, self.practice)
        self.assertIn("our last 2 sessions", body)

    def test_no_sessions_yields_no_intro(self):
        invoice = self._invoice_with_sessions([])
        _, body = get_invoice_email_content(invoice, self.practice)
        self.assertNotIn("Here is the invoice for", body)
        self.assertNotIn("{sessions_intro}", body)


class DocumentEmailContentTest(EmailContentBuilderTestBase):
    """The client-specific builders: (builder, subject, body marker)."""

    CASES = [
        (
            get_records_deletion_email_content,
            "Your records have been securely destroyed",
            "records retention period has ended",
        ),
        (
            get_questionnaire_pdf_email_content,
            "Questionnaire",
            "please find attached a short questionnaire",
        ),
    ]

    def test_subject_and_body(self):
        for builder, subject_expected, body_marker in self.CASES:
            with self.subTest(builder=builder.__name__):
                subject, body = builder(self.client_obj, self.practice)
                self.assertEqual(subject, subject_expected)
                self.assertIn(body_marker, body)
                self.assertTrue(body.startswith("Dear Jane,"))

    def test_signature_appended_when_set(self):
        for builder, *_ in self.CASES:
            with self.subTest(builder=builder.__name__):
                _, body = builder(self.client_obj, self.practice)
                self.assertTrue(body.endswith("-- \nBest regards\nAnna Schmidt"))

    def test_no_dangling_delimiter_when_signature_empty(self):
        self.practice.email_signature = ""
        for builder, *_ in self.CASES:
            with self.subTest(builder=builder.__name__):
                _, body = builder(self.client_obj, self.practice)
                self.assertNotIn("-- \n", body)


class TimeOffNoticeContentTest(EmailContentBuilderTestBase):
    """Returns subject and body for the editable multi-recipient form."""

    def _timeoff(self, start, end):
        return TimeOff.objects.create(start_date=start, end_date=end, title="Summer vacation")

    def test_single_period_same_month(self):
        periods = [self._timeoff(date(2026, 7, 24), date(2026, 7, 28))]
        subject, body = get_timeoff_notice_default_content(periods, self.practice)
        self.assertEqual(subject, "Practice closed: 24-28th July")
        self.assertIn("Fri 24th - Tue 28th July", body)

    def test_single_period_spanning_months(self):
        periods = [self._timeoff(date(2026, 6, 30), date(2026, 7, 2))]
        subject, _ = get_timeoff_notice_default_content(periods, self.practice)
        self.assertEqual(subject, "Practice closed: 30th June-2nd July")

    def test_multiple_periods_rendered_as_bullets(self):
        periods = [
            self._timeoff(date(2026, 7, 24), date(2026, 7, 28)),
            self._timeoff(date(2026, 8, 10), date(2026, 8, 14)),
        ]
        subject, body = get_timeoff_notice_default_content(periods, self.practice)
        self.assertIn("24-28th July", subject)
        self.assertIn("10-14th August", subject)
        self.assertIn("- Fri 24th - Tue 28th July", body)
        self.assertIn("- Mon 10th - Fri 14th August", body)

    def test_salutation_left_as_placeholder_for_per_recipient_render(self):
        """The body is filled in per recipient at send time, so it must stay a placeholder."""
        periods = [self._timeoff(date(2026, 7, 24), date(2026, 7, 28))]
        _, body = get_timeoff_notice_default_content(periods, self.practice)
        self.assertTrue(body.startswith("{salutation},"))
        rendered = render_email_template(body, {"salutation": "Dear Jane"})
        self.assertTrue(rendered.startswith("Dear Jane,"))

    def test_ordinal_suffixes(self):
        cases = {
            1: "1st",
            2: "2nd",
            3: "3rd",
            4: "4th",
            11: "11th",
            12: "12th",
            13: "13th",
            21: "21st",
        }
        for day, expected in cases.items():
            with self.subTest(day=day):
                periods = [self._timeoff(date(2026, 7, day), date(2026, 7, day))]
                subject, _ = get_timeoff_notice_default_content(periods, self.practice)
                self.assertIn(expected, subject)
