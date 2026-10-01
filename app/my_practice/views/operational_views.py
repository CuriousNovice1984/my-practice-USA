"""
Views for operational checklist feature (P-012).
Handles checklist display and completion tracking.
"""

import contextlib
from datetime import date, timedelta

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic import TemplateView

from ..models import ChecklistItemPause, OperationalChecklistCompletion

# Checklist items per type.
#
# IMPORTANT FOR SELF-HOSTERS: These items reflect one specific backup setup
# (LUKS-encrypted USB drive + NAS + MicroSD offsite rotation). The checklist
# engine (completion tracking, pausing, dashboard widget) is fully reusable —
# but you MUST replace the items below with steps that match your own backup
# and operational procedures. See docs/operations/SECURITY.md for context.
CHECKLIST_ITEMS: dict[str, list[dict[str, str]]] = {
    "weekly": [
        {"id": "connect_usb", "title": gettext_lazy("Connect external USB drive to laptop")},
        {
            "id": "run_backup",
            "title": gettext_lazy("Run backup command (./dev.py backup or scripts/backup.sh)"),
        },
        {"id": "verify_logs", "title": gettext_lazy("Check USB and NAS backup logs for errors")},
        {
            "id": "nas_trigger",
            "title": gettext_lazy("Confirm that NAS backup was triggered automatically"),
        },
        {"id": "disconnect_usb", "title": gettext_lazy("Safely disconnect USB drive")},
    ],
    "monthly": [
        {
            "id": "pick_source",
            "title": gettext_lazy("Pick a random backup source (USB or NAS)"),
        },
        {
            "id": "decrypt",
            "title": gettext_lazy("Decrypt backup (passphrase from sealed envelope)"),
        },
        {"id": "restore_db", "title": gettext_lazy("Restore database to test instance")},
        {
            "id": "verify_counts",
            "title": gettext_lazy("Compare invoice count & client count with production"),
        },
        {
            "id": "test_media",
            "title": gettext_lazy("Download a media file and verify checksum"),
        },
        {
            "id": "log_result",
            "title": gettext_lazy('Log result: "Restore test [DATE] [USB/NAS] [record count] "'),
        },
    ],
    "quarterly": [
        # Rotate every 2 weeks — alternate between Card A and Card B (UHS-I is fine, e.g. SanDisk Ultra / Samsung EVO Plus 32–64 GB)
        {
            "id": "pick_card",
            "title": gettext_lazy(
                "Take the other card from the cabinet (alternate Card A and Card B)"
            ),
        },
        {
            "id": "copy_backup",
            "title": gettext_lazy("Copy latest Pika-Backup snapshot to card"),
        },
        {
            "id": "encrypt_card",
            "title": gettext_lazy("Encrypt card (same passphrase as USB/NAS)"),
        },
        {
            "id": "test_restore",
            "title": gettext_lazy("Quick test: check 1–2 files + database count for readability"),
        },
        {
            "id": "label_card",
            "title": gettext_lazy('Label card: "Card A/B — [Date]"'),
        },
        {
            "id": "store_card",
            "title": gettext_lazy("Store in locked cabinet (location separate from laptop)"),
        },
    ],
    "annual": [
        {
            "id": "microsd_restore",
            "title": gettext_lazy("Full restore test from MicroSD (offsite scenario)"),
        },
        {
            "id": "update_check",
            "title": gettext_lazy("Check backup tool versions & security updates"),
        },
        {
            "id": "dpia_review",
            "title": gettext_lazy("Review DPIA document for processing changes"),
        },
        {
            "id": "audit_logs",
            "title": gettext_lazy("Review backup logs (no unexplained errors)"),
        },
        {
            "id": "refresh_plan",
            "title": gettext_lazy("Update emergency access plan (P-010) if needed"),
        },
    ],
}


def _get_period_start(checklist_type: str) -> date:
    """Calculate the first day of the current period for a checklist type."""
    today = timezone.localdate()
    if checklist_type == "weekly":
        return today - timedelta(days=today.weekday())  # Monday
    elif checklist_type == "monthly":
        return date(today.year, today.month, 1)
    elif checklist_type == "quarterly":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, quarter_start_month, 1)
    else:  # annual
        return date(today.year, 1, 1)


class OperationalChecklistView(TemplateView):
    """Display a checklist page for the given type and current period."""

    template_name = "my_practice/checklist.html"

    def get_context_data(self, **kwargs: object) -> dict:
        context = super().get_context_data(**kwargs)
        checklist_type = self.kwargs.get("checklist_type", "monthly")

        # Validate type
        valid_types: dict[str, str] = dict(OperationalChecklistCompletion.CHECKLIST_TYPES)
        if checklist_type not in valid_types:
            checklist_type = "monthly"

        period_start = _get_period_start(checklist_type)

        # Get or create the entry for this period (not yet completed)
        checklist, _created = OperationalChecklistCompletion.objects.get_or_create(
            checklist_type=checklist_type,
            year_month=period_start,
        )

        # Load active pauses and annotate each item
        active_pauses = {
            p.item_id: p
            for p in ChecklistItemPause.objects.filter(checklist_type=checklist_type)
            if p.is_active
        }
        annotated_items = [
            {**item, "pause": active_pauses.get(item["id"])}
            for item in CHECKLIST_ITEMS.get(checklist_type, [])
        ]

        context.update(
            {
                "checklist": checklist,
                "checklist_type": checklist_type,
                "checklist_type_display": valid_types[checklist_type],
                "items": annotated_items,
                "period_start": period_start,
                "all_types": list(valid_types.items()),
            }
        )
        return context


def checklist_complete(request: HttpRequest, checklist_type: str) -> HttpResponse:
    """Mark a checklist as completed for the current period."""
    if request.method != "POST":
        return redirect("checklist", checklist_type=checklist_type)

    valid_types: dict[str, str] = dict(OperationalChecklistCompletion.CHECKLIST_TYPES)
    if checklist_type not in valid_types:
        messages.error(request, _("Unknown checklist type."))
        return redirect("dashboard")

    period_start = _get_period_start(checklist_type)
    checklist = get_object_or_404(
        OperationalChecklistCompletion,
        checklist_type=checklist_type,
        year_month=period_start,
    )

    if checklist.is_completed:
        messages.info(
            request,
            _("%(type)s has already been completed.") % {"type": valid_types[checklist_type]},
        )
        return redirect("checklist", checklist_type=checklist_type)

    notes = request.POST.get("notes", "").strip()
    checklist.mark_complete(notes=notes)

    messages.success(
        request,
        _("%(type)s for %(period)s completed.")
        % {"type": valid_types[checklist_type], "period": period_start.strftime("%B %Y")},
    )
    return redirect("checklist", checklist_type=checklist_type)


def checklist_pause_item(request: HttpRequest, checklist_type: str, item_id: str) -> HttpResponse:
    """POST: Create or update a pause for a specific checklist item."""
    if request.method != "POST":
        return redirect("checklist", checklist_type=checklist_type)

    valid_types = dict(OperationalChecklistCompletion.CHECKLIST_TYPES)
    if checklist_type not in valid_types:
        return redirect("dashboard")

    valid_item_ids = {item["id"] for item in CHECKLIST_ITEMS.get(checklist_type, [])}
    if item_id not in valid_item_ids:
        messages.error(request, _("Unknown checklist item."))
        return redirect("checklist", checklist_type=checklist_type)

    reason = request.POST.get("reason", "").strip()
    paused_until_str = request.POST.get("paused_until", "").strip()
    paused_until = None
    if paused_until_str:
        from datetime import datetime

        with contextlib.suppress(ValueError):
            paused_until = datetime.strptime(paused_until_str, "%Y-%m-%d").date()

    ChecklistItemPause.objects.update_or_create(
        checklist_type=checklist_type,
        item_id=item_id,
        defaults={"reason": reason, "paused_until": paused_until},
    )
    messages.success(request, _("⏸ Item paused."))
    return redirect("checklist", checklist_type=checklist_type)


def checklist_unpause_item(request: HttpRequest, checklist_type: str, item_id: str) -> HttpResponse:
    """POST: Remove the pause for a specific checklist item."""
    if request.method != "POST":
        return redirect("checklist", checklist_type=checklist_type)

    ChecklistItemPause.objects.filter(checklist_type=checklist_type, item_id=item_id).delete()
    messages.success(request, _("▶️ Pause removed."))
    return redirect("checklist", checklist_type=checklist_type)


# Titles are UI chrome (translated); bodies are authored email content.
_BOILERPLATE_CARDS: list[dict] = [
    {
        "title": gettext_lazy("Private pay (no insurance billing)"),
        "id": "private-pay",
        "body": (
            "Hello,\n\n"
            "Please note that my practice is private pay: I don't bill insurance "
            "companies directly, and payment is due at the time of service.\n\n"
            "If your plan offers out-of-network benefits, you may be able to request "
            "reimbursement from your insurer yourself. I'm happy to provide a detailed "
            "receipt on request — please check with your plan about what it covers.\n\n"
            "Please feel free to contact me if you have any questions.\n\n"
            "Best regards"
        ),
    },
    {
        "title": gettext_lazy("Good Faith Estimate"),
        "id": "good-faith-estimate",
        "body": (
            "Hello,\n\n"
            "Under the No Surprises Act, you have the right to receive a Good Faith "
            "Estimate of the expected cost of your care if you are not using "
            "insurance.\n\n"
            "My fee is [amount] per [length]-minute session. Based on what we've "
            "discussed, I expect [number] sessions over the next [period], for an "
            "estimated total of [total]. This estimate is not a contract and the "
            "actual number of sessions may vary.\n\n"
            "If you are billed for more than $400 above this estimate, you have the "
            "right to dispute the bill. You can learn more at www.cms.gov/nosurprises.\n\n"
            "Best regards"
        ),
    },
    {
        "title": gettext_lazy("No opening / waitlist"),
        "id": "waitlist",
        "body": (
            "Hello,\n\n"
            "Thank you for reaching out. Unfortunately I don't have any openings at "
            "this time. I do keep a waitlist and would be glad to add you to it.\n\n"
            "I'll contact you as soon as a spot becomes available. Please note that "
            "this may take several months.\n\n"
            "If you need support sooner, the Psychology Today therapist directory can "
            "help you find another provider. If you are in crisis, please call or "
            "text 988 (Suicide & Crisis Lifeline), available 24/7.\n\n"
            "Best regards"
        ),
    },
    {
        "title": gettext_lazy("Reschedule / cancel appointment"),
        "id": "reschedule",
        "body": (
            "Hello,\n\n"
            "I'm writing regarding our appointment on [date]. Unfortunately I need "
            "to reschedule / cancel this appointment.\n\n"
            "I'd like to offer the following alternative times:\n"
            "– [Time 1]\n"
            "– [Time 2]\n\n"
            "Please let me know which works for you, or whether you'd prefer a "
            "different time.\n\n"
            "I apologize for the inconvenience and look forward to seeing you soon.\n\n"
            "Best regards"
        ),
    },
    {
        "title": gettext_lazy("Ending therapy"),
        "id": "termination",
        "body": (
            "Hello,\n\n"
            "As we discussed, our work together will conclude on [date]. Thank you "
            "for the trust you have placed in me.\n\n"
            "Should you ever need support again, please don't hesitate to get in "
            "touch. I wish you all the best going forward.\n\n"
            "Best regards"
        ),
    },
]


def boilerplate_view(request: HttpRequest) -> HttpResponse:
    """Display copyable email text templates (P-033)."""
    from django.shortcuts import render

    return render(request, "my_practice/boilerplate.html", {"cards": _BOILERPLATE_CARDS})
