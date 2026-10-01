"""
Client forms portal.

Public side (no login, reached through a private expiring link): the client
downloads the practice's blank forms and uploads completed ones, which land in
their documents for review. Staff side: create/revoke links, manage the blank
forms, and review new uploads.

Only the public views are meant to be exposed outside the tailnet (e.g. via
Tailscale Funnel on /portal/ — see docs/operations/CLIENT_PORTAL.md).
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..forms import PracticeFormUploadForm
from ..models import Client, ClientDocument
from ..models.portal import PortalLink, PracticeForm
from ..utils.file_processing import process_upload
from ..utils.practice_helpers import require_practice

logger = logging.getLogger(__name__)

# Per submission; the per-link total is PortalLink.uploads_remaining
MAX_FILES_PER_UPLOAD = 10
PORTAL_ACCEPT = ".pdf,.jpg,.jpeg,.png,.heic,.docx"


def _private(response: HttpResponse) -> HttpResponse:
    """Keep portal pages out of search engines, caches and outbound Referer headers."""
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response


def _link_or_gone(request: HttpRequest, token: str) -> PortalLink | HttpResponse:
    link = PortalLink.find_active(token)
    if link is None:
        return _private(render(request, "my_practice/portal_expired.html", status=404))
    return link


# ── Public (client-facing) ────────────────────────────────────────────────────


@login_not_required
def portal_home(request: HttpRequest, token: str) -> HttpResponse:
    """The client's upload page: blank forms to download plus an upload form."""
    link = _link_or_gone(request, token)
    if isinstance(link, HttpResponse):
        return link
    practice = link.client.practice
    practice_forms = PracticeForm.objects.filter(practice=practice, active=True)
    uploaded: list[str] = []
    errors: list[str] = []

    if request.method == "POST":
        uploaded, errors = _handle_upload(request, link, practice_forms)

    return _private(
        render(
            request,
            "my_practice/portal_home.html",
            {
                "link": link,
                "practice": practice,
                "practice_forms": practice_forms,
                "uploaded": uploaded,
                "errors": errors,
                "accept": PORTAL_ACCEPT,
                "max_files": min(MAX_FILES_PER_UPLOAD, link.uploads_remaining),
            },
        )
    )


def _handle_upload(request: HttpRequest, link: PortalLink, practice_forms) -> tuple[list, list]:
    """Store the submitted files as client documents. Returns (uploaded names, errors)."""
    files = request.FILES.getlist("files")
    if not files:
        return [], [_("Please choose at least one file.")]
    allowed = min(MAX_FILES_PER_UPLOAD, link.uploads_remaining)
    if len(files) > allowed:
        return [], [_("You can upload up to %(n)s files at a time.") % {"n": allowed}]

    form_id = request.POST.get("form")
    chosen = practice_forms.filter(pk=form_id).first() if form_id else None
    doc_type = chosen.document_type if chosen else ClientDocument.DocumentType.OTHER
    note = request.POST.get("note", "").strip()
    description = (chosen.title if chosen else note or _("Uploaded by client"))[:200]

    uploaded, errors = [], []
    for upload in files:
        try:
            stored = process_upload(upload)
        except ValueError as exc:
            errors.append(f"{upload.name}: {exc}")
            continue
        with transaction.atomic():
            doc = ClientDocument.objects.create(
                client=link.client,
                document_type=doc_type,
                file=stored,
                description=description,
                document_date=timezone.localdate(),
                uploaded_via_portal=True,
            )
            doc.complete_onboarding_step()
            PortalLink.objects.filter(pk=link.pk).update(
                upload_count=F("upload_count") + 1, last_used_at=timezone.now()
            )
        uploaded.append(upload.name)
    link.refresh_from_db()
    logger.info("Portal upload for %s: %d file(s)", link.client.client_code, len(uploaded))
    return uploaded, errors


@login_not_required
def portal_form_download(request: HttpRequest, token: str, form_id: int) -> HttpResponse:
    """Serve one of the practice's blank forms to the holder of a valid link."""
    link = _link_or_gone(request, token)
    if isinstance(link, HttpResponse):
        return link
    practice_form = get_object_or_404(
        PracticeForm, pk=form_id, practice=link.client.practice, active=True
    )
    try:
        handle = practice_form.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    return _private(
        FileResponse(handle, as_attachment=True, filename=practice_form.file.name.split("/")[-1])
    )


# ── Staff ─────────────────────────────────────────────────────────────────────


@require_POST
def portal_link_create(request: HttpRequest, pk: int) -> HttpResponse:
    """Create a new upload link for a client."""
    from django.conf import settings

    client = get_object_or_404(Client.objects.for_current_practice(request), pk=pk)
    try:
        days = int(request.POST.get("days", settings.PORTAL_LINK_DAYS))
    except ValueError:
        days = settings.PORTAL_LINK_DAYS
    days = max(1, min(days, 90))
    PortalLink.create_for(client, days)
    messages.success(
        request,
        _("Upload link created for %(code)s — valid for %(days)s days.")
        % {"code": client.client_code, "days": days},
    )
    return redirect(reverse("client_detail", kwargs={"pk": pk}) + "#client-portal")


@require_POST
def portal_link_revoke(request: HttpRequest, pk: int) -> HttpResponse:
    link = get_object_or_404(
        PortalLink, pk=pk, client__practice=request.current_practice, revoked_at__isnull=True
    )
    link.revoked_at = timezone.now()
    link.save(update_fields=["revoked_at", "updated_at"])
    messages.success(request, _("Upload link revoked."))
    return redirect(reverse("client_detail", kwargs={"pk": link.client_id}) + "#client-portal")


@require_practice
def portal_forms(request: HttpRequest) -> HttpResponse:
    """Manage the blank forms offered to clients in the portal."""
    practice = request.current_practice
    if request.method == "POST":
        form = PracticeFormUploadForm(request.POST, request.FILES)
        if form.is_valid():
            practice_form = form.save(commit=False)
            practice_form.practice = practice
            practice_form.save()
            messages.success(request, _("Form “%(title)s” added.") % {"title": practice_form})
            return redirect("portal_forms")
    else:
        form = PracticeFormUploadForm()
    return render(
        request,
        "my_practice/portal_forms.html",
        {"form": form, "practice_forms": PracticeForm.objects.filter(practice=practice)},
    )


@require_practice
@require_POST
def portal_form_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    practice_form = get_object_or_404(PracticeForm, pk=pk, practice=request.current_practice)
    practice_form.active = not practice_form.active
    practice_form.save(update_fields=["active", "updated_at"])
    return redirect("portal_forms")


@require_practice
@require_POST
def portal_form_delete(request: HttpRequest, pk: int) -> HttpResponse:
    practice_form = get_object_or_404(PracticeForm, pk=pk, practice=request.current_practice)
    practice_form.file.delete(save=False)
    practice_form.delete()
    messages.success(request, _("Form deleted."))
    return redirect("portal_forms")


@require_practice
def portal_uploads(request: HttpRequest) -> HttpResponse:
    """Documents clients uploaded through the portal that haven't been reviewed."""
    documents = (
        ClientDocument.objects.filter(
            client__practice=request.current_practice,
            uploaded_via_portal=True,
            reviewed_at__isnull=True,
        )
        .select_related("client")
        .order_by("created_at")
    )
    return render(request, "my_practice/portal_uploads.html", {"documents": documents})


@require_practice
@require_POST
def portal_upload_mark_reviewed(request: HttpRequest, pk: int) -> HttpResponse:
    document = get_object_or_404(
        ClientDocument, pk=pk, client__practice=request.current_practice, uploaded_via_portal=True
    )
    document.reviewed_at = timezone.now()
    document.save(update_fields=["reviewed_at", "updated_at"])
    next_url = request.POST.get("next")
    if next_url == "client":
        return redirect(
            reverse("client_detail", kwargs={"pk": document.client_id}) + "#client-portal"
        )
    return redirect("portal_uploads")
