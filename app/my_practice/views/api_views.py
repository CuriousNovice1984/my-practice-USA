"""
API views for the payments application.
"""

import base64
import os
import zipfile
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from PIL import Image
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

from ..models import Client, Invoice, Practice
from ..utils import get_next_invoice_number
from ..utils.practice_helpers import require_practice
from ..utils.questionnaire_content import QuestionnaireNotFoundError, load_questionnaire
from ..utils.view_helpers import safe_next


def next_invoice_number(request: HttpRequest) -> JsonResponse:
    """API endpoint to get next invoice number for a client"""
    client_id = request.GET.get("client")
    if not client_id:
        return JsonResponse({"error": _("Client ID required")}, status=400)

    try:
        client = Client.objects.for_current_practice(request).get(pk=client_id)
        suggested_number = get_next_invoice_number(client)
        return JsonResponse({"suggested_number": suggested_number})
    except Client.DoesNotExist:
        return JsonResponse({"error": _("Client not found")}, status=404)


# ---------------------------------------------------------------------------
# PDF helpers (shared between single-invoice and batch download)
# ---------------------------------------------------------------------------


def _prepare_practice_images(
    practice: Practice,
) -> tuple[str | None, str | None]:
    """
    Load and optimise practice logo and signature images.

    Returns:
        (logo_data, signature_data) as base64-encoded JPEG strings, or None
        if the image is missing.

    Cached per practice — decoding/resizing is the same work on every PDF a
    practice generates (invoice, contract, intake form, questionnaire) until
    the logo or signature file actually changes. The cache key includes both
    file names, so a re-upload (which Django always saves under a new name)
    invalidates it automatically; nothing needs to clear the cache by hand.
    """
    logo_name = getattr(practice.logo, "name", None) or ""
    signature_name = getattr(practice.signature, "name", None) or ""
    cache_key = f"practice_pdf_images:{practice.pk}:{logo_name}:{signature_name}"

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    logo_data: str | None = None
    signature_data: str | None = None

    for attr, max_size in (
        ("logo", (400, 160)),
        ("signature", (400, 160)),
    ):
        field = getattr(practice, attr, None)
        if not (field and os.path.exists(field.path)):
            continue
        img: Image.Image = Image.open(field.path)
        if img.mode in ("RGBA", "LA", "P"):
            # Composite onto paper background so transparent areas render
            # correctly in the PDF (plain convert("RGB") fills with black).
            bg = Image.new("RGBA", img.size, (251, 250, 246, 255))
            img = Image.alpha_composite(bg, img.convert("RGBA")).convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        if attr == "logo":
            logo_data = encoded
        else:
            signature_data = encoded

    result = (logo_data, signature_data)
    cache.set(cache_key, result, None)
    return result


def _render_invoice_pdf_bytes(
    invoice: Invoice,
    practice: Practice,
    logo_data: str | None,
    signature_data: str | None,
    font_config: FontConfiguration | None = None,
) -> tuple[bytes, str]:
    """
    Render a single invoice as a PDF in memory.

    Args:
        font_config: Optional shared FontConfiguration for batch rendering.
            Sharing one instance across multiple calls avoids repeated font
            loading from disk and speeds up batch PDF generation.

    Returns:
        (pdf_bytes, filename) where filename is suitable for download/zip entry.
    """
    template_name = "my_practice/invoice_pdf.html"
    filename = f"Invoice_{invoice.invoice_number}.pdf"

    ctx: dict = {
        "invoice": invoice,
        "practice": practice,
        "licenses": [lic for lic in practice.licenses.all() if lic.is_current()],
        "logo_data": logo_data,
        "signature_data": signature_data,
    }

    html_string = render_to_string(template_name, ctx)
    # base_url lets WeasyPrint resolve static font files (fonts/ dir) relative to the app
    base_url = f"file://{settings.BASE_DIR}/static/"
    pdf_bytes = HTML(string=html_string, base_url=base_url).write_pdf(font_config=font_config)
    return pdf_bytes, filename


def invoice_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate and download PDF for a single invoice."""
    invoice = get_object_or_404(Invoice.objects.for_current_practice(request), pk=pk)
    practice = invoice.practice

    logo_data, signature_data = _prepare_practice_images(practice)
    pdf_bytes, filename = _render_invoice_pdf_bytes(invoice, practice, logo_data, signature_data)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# Content files carry per-language text dicts; this app renders the English text.
QUESTIONNAIRE_LANG = "en"


def _resolve_questionnaire_section(
    section: dict, index: int, lang: str = QUESTIONNAIRE_LANG
) -> dict:
    """Resolve one raw content section to English text + pre-computed field names.

    Field names are prefixed by section index (``s{index}_...``) so multiple
    sections in one document never collide, and computed here rather than via
    nested Django ``forloop.parentloop`` chains, keeping the template simple.

    Supported ``type`` values: ``grid`` (statement rows x response columns;
    optionally multiple independent column groups per row, e.g. a
    "frequency" scale and a separate "duration" scale side by side),
    ``checklist`` (statement rows with a single yes/no checkbox), ``freetext``
    (a prompt with N blank fillable lines).
    """
    intro = section.get("intro", {}).get(lang, "")

    if section["type"] == "grid" and "column_groups" in section:
        column_groups = [
            {"label": g["label"][lang], "columns": [c[lang] for c in g["columns"]]}
            for g in section["column_groups"]
        ]
        rows = [
            {
                "label": item[lang],
                "groups": [
                    {
                        "field_name": f"s{index}_q{item_idx}_g{group_idx}",
                        "columns": group["columns"],
                    }
                    for group_idx, group in enumerate(column_groups)
                ],
            }
            for item_idx, item in enumerate(section["items"])
        ]
        return {"type": "grid", "intro": intro, "column_groups": column_groups, "rows": rows}

    if section["type"] == "grid":
        columns = [c[lang] for c in section["columns"]]
        rows = [
            {"label": item[lang], "field_name": f"s{index}_q{item_idx}"}
            for item_idx, item in enumerate(section["items"])
        ]
        return {"type": "grid", "intro": intro, "columns": columns, "rows": rows}

    if section["type"] == "checklist":
        rows = [
            {"label": item[lang], "field_name": f"s{index}_c{item_idx}"}
            for item_idx, item in enumerate(section["items"])
        ]
        return {"type": "checklist", "intro": intro, "rows": rows}

    if section["type"] == "freetext":
        n_lines = section.get("lines", 1)
        field_names = [f"s{index}_f{line_idx}" for line_idx in range(n_lines)]
        return {"type": "freetext", "intro": intro, "field_names": field_names}

    raise ValueError(f"Unknown questionnaire section type: {section['type']!r}")


def generate_questionnaire_pdf_bytes(code: str, practice: Practice) -> tuple[bytes, str]:
    """Render a blank clinical questionnaire (e.g. GAD-7) as fillable PDF bytes.

    This is not tied to a specific client — the same bytes apply to anyone. Content (question text, response
    scale) comes from ``load_questionnaire``, not this template, so instruments
    with restrictive licensing never need their text committed to this repo.

    Returns:
        (pdf_bytes, filename) — filename is suitable for download or attachment.
    """
    content = load_questionnaire(code)
    logo_data, _signature = _prepare_practice_images(practice)
    lang = QUESTIONNAIRE_LANG
    sections = [
        _resolve_questionnaire_section(section, index)
        for index, section in enumerate(content.sections)
    ]
    html_string = render_to_string(
        "my_practice/questionnaire_pdf.html",
        {
            "practice": practice,
            "logo_data": logo_data,
            "title": content.title[lang],
            "intro": content.intro.get(lang, ""),
            "sections": sections,
        },
    )
    pdf_bytes = HTML(string=html_string).write_pdf(pdf_forms=True)
    filename = f"{content.code.upper()}.pdf"
    return pdf_bytes, filename


@require_practice
def questionnaire_pdf(request: HttpRequest, code: str) -> HttpResponse:
    """Generate a blank, fillable clinical questionnaire PDF."""
    practice = request.current_practice
    try:
        pdf_bytes, filename = generate_questionnaire_pdf_bytes(code, practice)
    except QuestionnaireNotFoundError as e:
        messages.error(request, str(e))
        return redirect("dashboard")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_POST
def invoice_batch_download(request: HttpRequest) -> HttpResponse:
    """
    Generate a ZIP archive of invoice PDFs for the given year and status.

    POST parameters:
        year   — 4-digit year (required)
        status — invoice status to filter by (default: "paid")
    """
    year_raw = request.POST.get("year", "").strip()
    status = request.POST.get("status", Invoice.Status.PAID)

    if not year_raw or not year_raw.isdigit():
        messages.error(request, _("Invalid year for batch download."))
        return HttpResponse(status=400)

    year = int(year_raw)

    # Deliberately not InvoiceFilterHelper: that filters paid invoices by paid_date__year
    # (M-PAT-02), but this endpoint archives by invoice_date year regardless of status.
    invoices = (
        Invoice.objects.for_current_practice(request)
        .filter(invoice_date__year=year, status=status)
        .select_related("client")
        .order_by("invoice_date", "invoice_number")
    )

    if not invoices.exists():
        messages.warning(
            request,
            _("No invoices found for %(year)s with status '%(status)s'.")
            % {"year": year, "status": status},
        )
        return HttpResponse(status=204)

    practice = request.current_practice
    logo_data, signature_data = _prepare_practice_images(practice)

    # Share FontConfiguration across all renders to avoid repeated font loading from disk.
    font_config = FontConfiguration()

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for invoice in invoices:
            pdf_bytes, filename = _render_invoice_pdf_bytes(
                invoice, practice, logo_data, signature_data, font_config
            )
            # Prefix client code for easy sorting: AB-1_Invoice_AB-001.pdf
            entry_name = f"{invoice.client.client_code}_{filename}"
            zf.writestr(entry_name, pdf_bytes)

    zip_buffer.seek(0)
    zip_filename = f"Invoices_{year}.zip"
    response = HttpResponse(zip_buffer.read(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{zip_filename}"'
    return response


def update_invoice_status(request, pk):
    """Update invoice status via POST"""
    if request.method != "POST":
        return JsonResponse({"error": _("POST required")}, status=405)

    invoice = get_object_or_404(Invoice.objects.for_current_practice(request), pk=pk)
    new_status = request.POST.get("status")

    valid_statuses = {
        Invoice.Status.DRAFT,
        Invoice.Status.SENT,
        Invoice.Status.PAID,
        Invoice.Status.CANCELLED,
        Invoice.Status.WRITTEN_OFF,
    }
    if new_status not in valid_statuses:
        return JsonResponse({"error": _("Invalid status")}, status=400)

    invoice.status = new_status

    # Automatically set paid_date when status changes to paid
    if new_status == Invoice.Status.PAID and not invoice.paid_date:
        invoice.paid_date = timezone.localdate()
    # Clear paid_date if status is changed from paid to something else
    elif new_status != Invoice.Status.PAID and invoice.paid_date:
        invoice.paid_date = None

    invoice.save()

    # HTMX request: return just the badge HTML for #invoice-status-{pk}
    if request.headers.get("HX-Request"):
        badge_html = render_to_string(
            "includes/invoice_status_badge.html",
            {"invoice": invoice},
            request=request,
        )
        return HttpResponse(badge_html)

    messages.success(
        request,
        _("Status changed to: %(status)s") % {"status": invoice.get_status_display()},
    )

    next_url = safe_next(request, fallback="")
    if next_url:
        return redirect(next_url)

    return JsonResponse(
        {
            "status": new_status,
            "display": invoice.get_status_display(),
            "paid_date": (invoice.paid_date.strftime("%d %b %y") if invoice.paid_date else None),
        }
    )
