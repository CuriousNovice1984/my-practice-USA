"""
Scenes: the real photograph (and optional real footage) behind every page.

Each section of the app has its own photograph, shown as the page hero and,
blurred to a wash of colour, behind the whole page. The dashboard and sign-in
follow the time of day in the practice's time zone instead: morning, day, dusk
and night each have their own scene.

Every image is a real photograph and every clip real footage, self-hosted
under static/scenes/ (the app runs behind a tailnet and makes no outbound
calls), processed with scripts/scene_media.py. Provenance and license for each
one is recorded here and in static/scenes/CREDITS.md; keep the two in sync when
adding a scene.

A scene with footage plays it in place of the photograph while ambient motion
is on; the photograph remains for anyone with motion off.
"""

from dataclasses import dataclass

from django.utils import timezone
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Footage:
    """Real video for a scene: <key>.mp4 and <key>-poster.webp."""

    place: str | Promise
    author: str
    source_url: str
    license: str


@dataclass(frozen=True)
class Scene:
    key: str
    alt: str | Promise
    place: str | Promise
    photographer: str
    source_url: str
    license: str
    # object-position for the wide hero crop, so the subject survives it
    focus: str = "50% 50%"
    footage: Footage | None = None

    @property
    def base(self) -> str:
        return f"scenes/{self.key}"

    @property
    def video(self) -> bool:
        return self.footage is not None


UNSPLASH = "Unsplash License"
CC0 = "CC0 (public domain)"
MIXKIT = "Mixkit Stock Video Free License"

SCENES: dict[str, Scene] = {
    scene.key: scene
    for scene in (
        # ── Time of day (dashboard, sign-in) ──────────────────────────────
        Scene(
            "dawn",
            _("A still lake below snow-capped mountains in early light"),
            _("Morning on a mountain lake"),
            "Peter Thomas",
            "https://unsplash.com/photos/Dxod5pdRtsk",
            UNSPLASH,
            "50% 55%",
            Footage(
                _("Sunrise over a misty valley"),
                "Mixkit",
                "https://mixkit.co/free-stock-video/beautiful-sunrise-landscape-1944/",
                MIXKIT,
            ),
        ),
        Scene(
            "day",
            _("Snow-capped peaks rising above Lake Sherburne"),
            _("Lake Sherburne, Glacier National Park"),
            "Jacob W. Frank, NPS",
            "https://github.com/BuddiesOfBudgie/budgie-backgrounds",
            CC0,
            "50% 40%",
            Footage(
                _("Clouds drifting over green hills"),
                "Mixkit",
                "https://mixkit.co/free-stock-video/time-lapse-of-a-green-meadow-4070/",
                MIXKIT,
            ),
        ),
        Scene(
            "dusk",
            _("A wooden pier reaching into calm water at sunset"),
            _("Sunset by the pier"),
            "Paul Carmona",
            "https://unsplash.com/photos/ces8_Bo7bhQ",
            CC0,
            "50% 50%",
            Footage(
                _("Sunset over a bay of islands"),
                "Mixkit",
                "https://mixkit.co/free-stock-video/beautiful-sunset-on-a-bay-from-above-4999/",
                MIXKIT,
            ),
        ),
        Scene(
            "night",
            _("Half Dome under a sky full of stars"),
            _("Half Dome at night, Yosemite"),
            "Ian Beckley",
            "https://www.pexels.com/photo/photo-of-snow-capped-mountain-during-evening-2440024/",
            "Pexels License",
            "50% 45%",
            Footage(
                _("The Milky Way over the mountains"),
                "Mixkit",
                "https://mixkit.co/free-stock-video/milky-way-seen-at-night-4148/",
                MIXKIT,
            ),
        ),
        # ── Sections ──────────────────────────────────────────────────────
        Scene(
            "clients",
            _("Rolling tea gardens fading into morning mist"),
            _("Tea gardens in the mist"),
            "Wikimedia Commons",
            "https://github.com/BuddiesOfBudgie/budgie-backgrounds",
            CC0,
            "50% 60%",
        ),
        Scene(
            "sessions",
            _("Fern fronds unfolding in deep shade"),
            _("Ferns"),
            "Nick Cooper",
            "https://unsplash.com/photos/_1UF_3TlKcQ",
            UNSPLASH,
        ),
        Scene(
            "supervision",
            _("A green heron perched quietly at the water's edge"),
            _("Heron, Merritt Island, Florida"),
            "Budgie Backgrounds",
            "https://github.com/BuddiesOfBudgie/budgie-backgrounds",
            CC0,
            "40% 25%",
        ),
        Scene(
            "invoices",
            _("Yosemite Valley in autumn, seen from Tunnel View"),
            _("Tunnel View, Yosemite"),
            "Aniket Deole",
            "https://unsplash.com/photos/M6XC789HLe8",
            UNSPLASH,
        ),
        Scene(
            "analytics",
            _("The layered walls of the Grand Canyon at dusk"),
            _("Grand Canyon at dusk"),
            "Jad Limcaco",
            "https://unsplash.com/photos/JEq_2UJoTtg",
            CC0,
            "50% 55%",
        ),
        Scene(
            "tax",
            _("Granite ridges dusted with snow under a pale sky"),
            _("Granite ridges above Canazei"),
            "Benjamin Voros",
            "https://unsplash.com/photos/yrwpJwDNSHE",
            CC0,
            "50% 35%",
        ),
        Scene(
            "finance",
            _("Light falling into the curved sandstone of Antelope Canyon"),
            _("Antelope Canyon, Arizona"),
            "Ashim D'Silva",
            "https://unsplash.com/photos/WeYamle9fDM",
            CC0,
            "50% 40%",
        ),
        Scene(
            "timeoff",
            _("Turquoise surf washing onto a beach, seen from above"),
            _("Surf from above"),
            "Nattu Adnan",
            "https://unsplash.com/photos/Ai2TRdvI6gM",
            UNSPLASH,
            "50% 45%",
        ),
        Scene(
            "inquiries",
            _("A trail of footprints crossing a sand dune"),
            _("Footprints in the dunes"),
            "David Emrich",
            "https://unsplash.com/photos/A9mr3TPoj0k",
            UNSPLASH,
            "50% 65%",
        ),
        Scene(
            "focus",
            _("A single jellyfish glowing in deep blue water"),
            _("Jellyfish in deep water"),
            "Ng",
            "https://unsplash.com/photos/bviex5lwf3s",
            CC0,
            "50% 55%",
        ),
        Scene(
            "licenses",
            _("The buttes of Monument Valley under scattered clouds"),
            _("Monument Valley, on the Utah–Arizona border"),
            "Jasper van der Meij",
            "https://unsplash.com/photos/eKpO8DlBvo0",
            CC0,
            "50% 45%",
        ),
        Scene(
            "portal",
            _("Soft yellow petals against a pale sky"),
            _("Petals and sky"),
            "Martin Adams",
            "https://unsplash.com/photos/MpTdvXlAsVE",
            UNSPLASH,
            "0% 70%",
        ),
        Scene(
            "settings",
            _("Desert mountains mirrored in perfectly still water"),
            _("Still water"),
            "Sean Afnan",
            "https://unsplash.com/photos/i17Ln-C-qhE",
            CC0,
        ),
        Scene(
            "notfound",
            _("Wind-shaped sand dunes beneath a deep blue sky"),
            _("Dunes at dusk"),
            "Jared Evans",
            "https://unsplash.com/photos/Wwg1TzCuV9E",
            CC0,
            "50% 65%",
        ),
        Scene(
            "tags",
            _("Small blue flowers in a dark green meadow"),
            _("Blue periwinkle"),
            "Wikimedia Commons",
            "https://github.com/BuddiesOfBudgie/budgie-backgrounds",
            CC0,
        ),
    )
}

# url_name prefix → scene. First match wins, so more specific prefixes go first.
SECTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("portal_", "portal"),
    ("send_portal_link", "portal"),
    ("license_", "licenses"),
    ("client_triage", "clients"),
    ("client_", "clients"),
    ("suggest_client", "clients"),
    ("session_", "sessions"),
    ("calendar_", "sessions"),
    ("supervision_", "supervision"),
    ("invoice_", "invoices"),
    ("monthly_billing", "invoices"),
    ("billing_", "invoices"),
    ("send_invoice", "invoices"),
    ("send_payment", "invoices"),
    ("send_cancellation", "sessions"),
    ("send_questionnaire", "clients"),
    ("questionnaire_", "clients"),
    ("update_invoice", "invoices"),
    ("analytics", "analytics"),
    ("practice_analysis", "analytics"),
    ("revenue_", "analytics"),
    ("tax_", "tax"),
    ("save_tax", "tax"),
    ("expense_", "finance"),
    ("withdrawal_", "finance"),
    ("bank_", "finance"),
    ("plaid_", "finance"),
    ("timeoff_", "timeoff"),
    ("inquiry_", "inquiries"),
    ("marketing_", "inquiries"),
    ("focus_", "focus"),
    ("todo_", "focus"),
    ("tag_", "tags"),
)

TIME_OF_DAY_PAGES = {"home", "dashboard", "login"}
DEFAULT_SCENE = "settings"


def time_of_day(hour: int) -> str:
    """Scene key for an hour of the day (0-23) in the practice's time zone."""
    if 5 <= hour < 12:
        return "dawn"
    if 12 <= hour < 17:
        return "day"
    if 17 <= hour < 21:
        return "dusk"
    return "night"


def greeting(hour: int) -> str:
    """The assistant's greeting for an hour of the day."""
    if 5 <= hour < 12:
        return str(_("Good morning"))
    if 12 <= hour < 17:
        return str(_("Good afternoon"))
    return str(_("Good evening"))


def scene_for(url_name: str | None, hour: int | None = None) -> Scene:
    """The scene for a page, identified by its URL name."""
    if url_name in TIME_OF_DAY_PAGES:
        if hour is None:
            hour = timezone.localtime().hour
        return SCENES[time_of_day(hour)]
    for prefix, key in SECTION_PREFIXES:
        if url_name and url_name.startswith(prefix):
            return SCENES[key]
    return SCENES[DEFAULT_SCENE]
