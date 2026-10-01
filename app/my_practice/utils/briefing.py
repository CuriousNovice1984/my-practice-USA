"""
The assistant's daily briefing at the top of the dashboard.

A handful of plain-language lines about today, in the order a person would want
them: the day's sessions first, then anything that needs attention, then the
quiet confirmations. Each line links to where it can be dealt with. Client
codes only, never names — the briefing sits in the hero, which privacy mode
does not blur.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format, time_format
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from ..models import ClientDocument, ClientInquiry, PracticeTodo, Session
from ..models.inquiry import InquiryStatus
from .formatting import format_currency_rounded
from .licensure import licenses_needing_attention


@dataclass(frozen=True)
class BriefingItem:
    text: str
    url: str
    # "attention" lines are tinted and counted in the summary; "calm" ones are not
    tone: str = "calm"


@dataclass
class Briefing:
    items: list[BriefingItem] = field(default_factory=list)

    @property
    def attention_count(self) -> int:
        return sum(1 for item in self.items if item.tone == "attention")

    @property
    def summary(self) -> str:
        count = self.attention_count
        if not count:
            return _("Everything is in order. Enjoy the quiet.")
        return ngettext(
            "One thing could use your attention.",
            "%(count)s things could use your attention.",
            count,
        ) % {"count": count}


def _sessions_line(practice, today: date, now: datetime) -> BriefingItem:
    sessions = list(
        Session.objects.filter(client__practice=practice, session_date=today, cancelled=False)
        .select_related("client")
        .order_by("session_time")
    )
    url = reverse("dashboard") + "#widget-weekly_focus"
    if not sessions:
        return BriefingItem(_("No sessions on the calendar today."), url)
    count = len(sessions)
    upcoming = [s for s in sessions if s.session_time and s.session_time >= now.time()]
    if upcoming:
        nxt = upcoming[0]
        text = ngettext(
            "%(count)s session today. Next at %(time)s with %(code)s.",
            "%(count)s sessions today. Next at %(time)s with %(code)s.",
            count,
        ) % {
            "count": count,
            "time": time_format(nxt.session_time, "g:i A"),
            "code": nxt.client.client_code,
        }
    else:
        text = ngettext(
            "%(count)s session today, and it's behind you.",
            "%(count)s sessions today, all behind you.",
            count,
        ) % {"count": count}
    return BriefingItem(text, url)


def build_briefing(
    practice, status_stats: dict, today: date | None = None, now: datetime | None = None
) -> Briefing:
    """Assemble today's briefing for a practice.

    ``status_stats`` is RevenueCalculator.get_status_breakdown() for the practice
    (M-PAT-02), which the dashboard has already computed.
    """
    now = now or timezone.localtime()
    today = today or now.date()
    briefing = Briefing()
    briefing.items.append(_sessions_line(practice, today, now))

    due = (
        PracticeTodo.objects.filter(
            practice=practice, completed_at__isnull=True, due_date__lte=today
        )
        .exclude(snoozed_until__gte=today)
        .count()
    )
    if due:
        briefing.items.append(
            BriefingItem(
                ngettext(
                    "%(count)s task is due in your focus queue.",
                    "%(count)s tasks are due in your focus queue.",
                    due,
                )
                % {"count": due},
                reverse("focus_queue"),
                "attention",
            )
        )

    uploads = ClientDocument.objects.filter(
        client__practice=practice, uploaded_via_portal=True, reviewed_at__isnull=True
    ).count()
    if uploads:
        briefing.items.append(
            BriefingItem(
                ngettext(
                    "A client sent %(count)s new document through the portal.",
                    "Clients sent %(count)s new documents through the portal.",
                    uploads,
                )
                % {"count": uploads},
                reverse("portal_uploads"),
                "attention",
            )
        )

    for lic in licenses_needing_attention(practice):
        if lic.is_expired:
            text = _("Your %(state)s license has expired.") % {"state": lic.get_state_display()}
        else:
            text = _("Your %(state)s license expires on %(date)s.") % {
                "state": lic.get_state_display(),
                "date": date_format(lic.expiration_date, "d M y"),
            }
        briefing.items.append(BriefingItem(text, reverse("license_list"), "attention"))

    inquiries = ClientInquiry.objects.filter(practice=practice, status=InquiryStatus.NEW).count()
    if inquiries:
        briefing.items.append(
            BriefingItem(
                ngettext(
                    "%(count)s new inquiry is waiting for a reply.",
                    "%(count)s new inquiries are waiting for a reply.",
                    inquiries,
                )
                % {"count": inquiries},
                reverse("inquiry_list"),
                "attention",
            )
        )

    drafts = status_stats["draft"]["count"] or 0
    if drafts:
        briefing.items.append(
            BriefingItem(
                ngettext(
                    "%(count)s draft invoice is ready to send.",
                    "%(count)s draft invoices are ready to send.",
                    drafts,
                )
                % {"count": drafts},
                reverse("invoice_list") + "?status=draft",
            )
        )

    unpaid = status_stats["sent"]["count"] or 0
    if unpaid:
        briefing.items.append(
            BriefingItem(
                ngettext(
                    "%(count)s invoice is awaiting payment (%(amount)s).",
                    "%(count)s invoices are awaiting payment (%(amount)s).",
                    unpaid,
                )
                % {
                    "count": unpaid,
                    "amount": format_currency_rounded(status_stats["sent"]["total"] or 0),
                },
                reverse("billing_open_overview"),
            )
        )
    return briefing
