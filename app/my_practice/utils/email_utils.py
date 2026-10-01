"""
Email content builders for client-facing emails (invoices, questionnaires,
time-off notices, record deletion notices).
"""

from typing import TYPE_CHECKING, Any

from ..validators import PLACEHOLDER_RE
from .formatting import format_currency

if TYPE_CHECKING:
    from ..models import Client, Invoice, Practice, TimeOff


def _build_sessions_intro(invoice: "Invoice") -> str:
    """Return an opening sentence summarising which sessions the invoice covers.

    Returns text with a trailing newline pair (ready to embed in a template block)
    or empty string if no sessions are attached to the invoice.
    """
    from datetime import date

    session_dates = [
        item.session.session_date
        for item in invoice.items.select_related("session").all()
        if item.session_id
    ]

    if not session_dates:
        return ""

    months = {(d.year, d.month) for d in session_dates}
    n = len(session_dates)
    session_word = "session" if n == 1 else "sessions"

    if len(months) == 1:
        year, month = next(iter(months))
        month_name = date(year, month, 1).strftime("%B")
        sentence = f"Here is the invoice for our {session_word} in {month_name}."
    else:
        sentence = f"Here is the invoice for our last {n} {session_word}."

    return sentence + "\n\n"


def _with_signature(body: str, practice: "Practice") -> str:
    """Append the practice signature with the standard "-- " delimiter, if one is set."""
    if practice.email_signature:
        return body + "\n\n-- \n" + practice.email_signature
    return body


def get_salutation_for_client(client: "Client") -> str:
    """
    Get email salutation for a client.
    Returns the custom salutation if set, otherwise "Dear {first name}".
    """
    if client.salutation:
        return client.salutation

    first_name = client.full_name.split()[0] if client.full_name else "Client"
    return f"Dear {first_name}"


def render_email_template(template_text: str, context: dict[str, Any]) -> str:
    """
    Render email template by replacing placeholders.

    Supported placeholders:
    - {salutation}: Client salutation
    - {invoice_number}: Invoice number
    - {amount}: Formatted amount with currency
    - {date}: Formatted date
    - {client_name}: Client full name

    Deliberately *total*: it never raises, whatever the template contains.
    Templates are free text typed by the practitioner — the DB-configured
    invoice templates in Practice settings, and the time-off notice body typed
    straight into a form — so a typo'd ``{Betrag}`` or a stray ``{`` in ordinary
    prose used to abort the send with KeyError/ValueError. In the time-off loop
    that happened outside the per-recipient try/except, i.e. mid-send, after
    some clients had already been emailed.

    Unknown ``{placeholders}`` and unmatched braces are therefore left standing
    verbatim rather than raising. Save-time validation is what tells the
    practitioner about a typo, while they can still fix it — see
    ``validate_email_template_placeholders`` on the Practice template fields.

    Note this replaces ``str.format``, so ``{{`` is no longer an escape for a
    literal brace (nothing in the app relied on it) and attribute/index
    traversal like ``{client.__class__}`` is no longer reachable from template
    text at all.
    """
    return PLACEHOLDER_RE.sub(
        lambda m: str(context[m.group(1)]) if m.group(1) in context else m.group(0),
        template_text,
    )


def prepare_invoice_email_context(
    invoice: "Invoice", practice: "Practice", custom_salutation: str | None = None
) -> dict[str, str]:
    """
    Prepare context dict for invoice email templates.

    Args:
        invoice: Invoice instance
        practice: Practice instance
        custom_salutation: Optional custom salutation override

    Returns:
        dict with all template placeholders
    """
    salutation = custom_salutation or get_salutation_for_client(invoice.client)

    return {
        "salutation": salutation,
        "invoice_number": invoice.invoice_number,
        # Same formatter as the |currency filter used by the attached PDF
        "amount": format_currency(invoice.total),
        "date": invoice.invoice_date.strftime("%d %b %y"),
        "client_name": invoice.client.full_name,
    }


def get_invoice_email_content(
    invoice: "Invoice", practice: "Practice", custom_message: str | None = None
) -> tuple[str, str]:
    """
    Get complete email content (subject, body) for an invoice.

    Args:
        invoice: Invoice instance
        practice: Practice instance
        custom_message: Optional custom message to append to body

    Returns:
        tuple: (subject, body)
    """
    context = prepare_invoice_email_context(invoice, practice)
    context["sessions_intro"] = _build_sessions_intro(invoice)

    subject = render_email_template(practice.invoice_email_subject, context)
    body = render_email_template(practice.invoice_email_body, context)

    if custom_message:
        body = body + "\n\n" + custom_message

    return subject, _with_signature(body, practice)


def get_records_deletion_email_content(client: "Client", practice: "Practice") -> tuple[str, str]:
    """Return (subject, body) notifying a former client that their records were destroyed."""
    salutation = get_salutation_for_client(client)
    subject = "Your records have been securely destroyed"
    body = (
        f"{salutation},\n\n"
        "I'm writing to let you know that the records from our work together have been "
        "securely destroyed, as the required records retention period has ended.\n\n"
        "I hope you are well."
    )
    return subject, _with_signature(body, practice)


def get_questionnaire_pdf_email_content(client: "Client", practice: "Practice") -> tuple[str, str]:
    """Get default email content (subject, body) for sending a questionnaire PDF.

    Returns:
        tuple: (subject, body)
    """
    salutation = get_salutation_for_client(client)
    subject = "Questionnaire"
    body = (
        f"{salutation},\n\n"
        "please find attached a short questionnaire. You can fill it in "
        "directly in the PDF or by hand. "
        "Please send it back to me or simply bring it to our next session.\n\n"
        "Feel free to get in touch at any time if you have any questions."
    )
    return subject, _with_signature(body, practice)


def _ordinal_suffix(day: int) -> str:
    if 11 <= (day % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def _same_month(t: "TimeOff") -> bool:
    return (t.start_date.year, t.start_date.month) == (t.end_date.year, t.end_date.month)


def _format_period_subject(t: "TimeOff") -> str:
    """Compact date range for the subject line, e.g. '24-28th July' or '30th Jun-2nd Jul'."""
    start, end = t.start_date, t.end_date
    end_str = f"{end.day}{_ordinal_suffix(end.day)}"
    if _same_month(t):
        return f"{start.day}-{end_str} {end.strftime('%B')}"
    start_str = f"{start.day}{_ordinal_suffix(start.day)}"
    return f"{start_str} {start.strftime('%B')}-{end_str} {end.strftime('%B')}"


def _format_period_body(t: "TimeOff") -> str:
    """Weekday-annotated date range for the body, e.g. 'Fri 24th - Tue 28th July'."""
    start, end = t.start_date, t.end_date
    start_str = f"{start.strftime('%a')} {start.day}{_ordinal_suffix(start.day)}"
    end_str = f"{end.strftime('%a')} {end.day}{_ordinal_suffix(end.day)}"
    if _same_month(t):
        return f"{start_str} - {end_str} {end.strftime('%B')}"
    return f"{start_str} {start.strftime('%B')} - {end_str} {end.strftime('%B')}"


def get_timeoff_notice_default_content(
    time_offs: list["TimeOff"], practice: "Practice"
) -> tuple[str, str]:
    """Get default email content for a time-off heads-up notice.

    Accepts one or more time-off periods (e.g. several separate holidays
    announced in a single email) and summarises them either as a single
    date range (one period) or a bulleted list of ranges (several periods).

    Content is deliberately date-only, not title-based: clients don't need to
    know what the practitioner is doing with the time, just which dates and
    weekdays are affected, so they can scan for their own recurring slot.

    Unlike the other builders here, this one is not rendered for a single client:
    it's used to pre-fill an editable multi-recipient form. The body contains a
    literal ``{salutation}`` placeholder that is filled in per-recipient at send
    time via render_email_template(), the same mechanism used for the
    DB-configurable invoice email templates above.

    Returns:
        tuple: (subject, body)
    """
    subject = f"Practice closed: {', '.join(_format_period_subject(t) for t in time_offs)}"

    if len(time_offs) == 1:
        periods = _format_period_body(time_offs[0])
    else:
        periods = "\n".join(f"- {_format_period_body(t)}" for t in time_offs)

    body = (
        "{salutation},\n\n"
        "I wanted to give you advance notice: the practice will be closed:\n\n"
        f"{periods}\n\n"
        "I won't be reachable during this time. If anything urgent comes up, "
        "please get in touch beforehand.\n\n"
        "All the best until then."
    )

    return subject, _with_signature(body, practice)
