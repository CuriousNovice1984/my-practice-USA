"""Tests for the photographic shell: scenes, their assets and credits, the shell
template tags, the dashboard briefing and the pages that render them."""

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import get_resolver, reverse
from django.utils import timezone

from ..models import (
    Client,
    ClientDocument,
    ClientInquiry,
    Practice,
    PracticeTodo,
    ProviderLicense,
    Session,
    UserPractice,
)
from ..models.inquiry import InquirySource, InquiryStatus
from ..scenes import SCENES, SECTION_PREFIXES, Scene, greeting, scene_for, time_of_day
from ..templatetags.icons import PATHS, icon
from ..templatetags.scene_tags import scene_image, scene_video, strip_emoji
from ..utils.briefing import build_briefing

SCENE_DIR = Path(settings.BASE_DIR) / "static" / "scenes"
# Footage ships in the repo and to every page load with motion on: keep it light.
MAX_CLIP_BYTES = 8 * 1024 * 1024
MAX_POSTER_BYTES = 300 * 1024
EMPTY_STATS = {
    "draft": {"count": 0, "total": Decimal("0")},
    "sent": {"count": 0, "total": Decimal("0")},
    "paid": {"count": 0, "total": Decimal("0")},
    "cancelled": {"count": 0, "total": Decimal("0")},
}


class TimeOfDayTests(SimpleTestCase):
    def test_hour_boundaries(self):
        expected = {0: "night", 4: "night", 5: "dawn", 11: "dawn", 12: "day", 16: "day"}
        expected |= {17: "dusk", 20: "dusk", 21: "night", 23: "night"}
        for hour, key in expected.items():
            with self.subTest(hour=hour):
                self.assertEqual(time_of_day(hour), key)

    def test_greeting_follows_the_clock(self):
        self.assertEqual(greeting(8), "Good morning")
        self.assertEqual(greeting(13), "Good afternoon")
        self.assertEqual(greeting(19), "Good evening")
        self.assertEqual(greeting(2), "Good evening")


class SceneMappingTests(SimpleTestCase):
    def test_dashboard_and_sign_in_follow_the_time_of_day(self):
        self.assertEqual(scene_for("dashboard", hour=8).key, "dawn")
        self.assertEqual(scene_for("home", hour=14).key, "day")
        self.assertEqual(scene_for("login", hour=22).key, "night")

    def test_sections(self):
        cases = {
            "client_detail": "clients",
            "client_triage": "clients",
            "session_log_create": "sessions",
            "calendar_import": "sessions",
            "supervision_queue": "supervision",
            "invoice_detail": "invoices",
            "monthly_billing_overview": "invoices",
            "analytics": "analytics",
            "revenue_report": "analytics",
            "tax_quarter_overview": "tax",
            "plaid_home": "finance",
            "expense_list": "finance",
            "timeoff_list": "timeoff",
            "inquiry_list": "inquiries",
            "focus_queue": "focus",
            "todo_create": "focus",
            "license_list": "licenses",
            "portal_home": "portal",
            "send_portal_link_email": "portal",
            "tag_list": "tags",
            "practice_edit": "settings",
        }
        for url_name, key in cases.items():
            with self.subTest(url_name=url_name):
                self.assertEqual(scene_for(url_name).key, key)

    def test_unknown_page_falls_back(self):
        self.assertEqual(scene_for(None).key, "settings")

    def test_every_prefix_points_at_a_real_scene(self):
        for prefix, key in SECTION_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertIn(key, SCENES)

    def test_every_named_url_gets_a_scene(self):
        names = [name for name in get_resolver().reverse_dict if isinstance(name, str)]
        self.assertGreater(len(names), 50)
        for name in names:
            self.assertIsInstance(scene_for(name, hour=9), Scene)


class SceneAssetTests(SimpleTestCase):
    """Guardrail: every scene ships its files and its credit, and nothing is orphaned.

    A missing file is a broken hero on one section only, which nobody notices
    until they happen to open that page; a missing credit is a license problem
    nobody notices at all.
    """

    def test_every_scene_has_its_image_files(self):
        for scene in SCENES.values():
            for suffix in ("-2560.webp", "-1280.webp", "-ambient.webp"):
                with self.subTest(scene=scene.key, suffix=suffix):
                    self.assertIsNotNone(finders.find(f"{scene.base}{suffix}"))

    def test_footage_matches_the_video_flag(self):
        for scene in SCENES.values():
            has_mp4 = finders.find(f"{scene.base}.mp4") is not None
            with self.subTest(scene=scene.key):
                self.assertEqual(has_mp4, scene.video, "give the scene Footage to match the files")
                if scene.video:
                    self.assertIsNotNone(finders.find(f"{scene.base}-poster.webp"))

    def test_footage_stays_light(self):
        """The large-file pre-commit hook exempts scene clips; this is their ceiling."""
        for scene in SCENES.values():
            if not scene.video:
                continue
            with self.subTest(scene=scene.key):
                self.assertLessEqual(
                    (SCENE_DIR / f"{scene.key}.mp4").stat().st_size, MAX_CLIP_BYTES
                )
                poster = SCENE_DIR / f"{scene.key}-poster.webp"
                self.assertLessEqual(poster.stat().st_size, MAX_POSTER_BYTES)

    def test_no_orphaned_files(self):
        pattern = re.compile(
            r"^(?P<key>[a-z]+)(-2560\.webp|-1280\.webp|-ambient\.webp|\.mp4|-poster\.webp)$"
        )
        for path in SCENE_DIR.iterdir():
            if path.name == "CREDITS.md":
                continue
            match = pattern.match(path.name)
            with self.subTest(file=path.name):
                self.assertIsNotNone(match, "unexpected file name")
                self.assertIn(match["key"], SCENES)

    def test_every_scene_is_credited(self):
        credits = (SCENE_DIR / "CREDITS.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"^\| `([a-z]+)` \|", credits, re.M))
        self.assertEqual(listed, set(SCENES))
        for scene in SCENES.values():
            with self.subTest(scene=scene.key):
                self.assertTrue(scene.license)
                self.assertTrue(scene.source_url.startswith("https://"))

    def test_every_clip_is_credited(self):
        credits = (SCENE_DIR / "CREDITS.md").read_text(encoding="utf-8")
        footage_section = credits.split("## Footage", 1)[1].split("\nCollections:", 1)[0]
        listed = set(re.findall(r"^\| `([a-z]+)` \|", footage_section, re.M))
        self.assertEqual(listed, {key for key, scene in SCENES.items() if scene.video})
        for scene in SCENES.values():
            if scene.footage:
                with self.subTest(scene=scene.key):
                    self.assertIn(scene.footage.source_url, footage_section)
                    self.assertTrue(scene.footage.license)


class SceneTagTests(SimpleTestCase):
    def test_scene_image_is_responsive_and_cropped(self):
        html = scene_image(SCENES["focus"])
        self.assertIn("focus-1280.webp 1280w", html)
        self.assertIn("focus-2560.webp 2560w", html)
        self.assertIn('style="object-position: 50% 55%"', html)
        self.assertIn('fetchpriority="high"', html)
        self.assertIn("jellyfish", html)

    def test_lazy_images_skip_fetch_priority(self):
        self.assertNotIn("fetchpriority", scene_image(SCENES["focus"], loading="lazy"))

    def test_no_video_markup_without_footage(self):
        self.assertEqual(scene_video(SCENES["focus"]), "")

    def test_video_source_is_deferred_until_motion_is_allowed(self):
        html = scene_video(SCENES["dawn"])
        self.assertIn('data-src="/static/scenes/dawn.mp4"', html)
        self.assertIn('poster="/static/scenes/dawn-poster.webp"', html)
        self.assertNotIn(" src=", html)
        self.assertNotIn("autoplay", html)
        self.assertIn("muted", html)

    def test_strip_emoji(self):
        self.assertEqual(strip_emoji("🏦 Bank connection"), "Bank connection")
        self.assertEqual(strip_emoji("⚠️ Check this"), "Check this")
        self.assertEqual(strip_emoji("← Back"), "← Back")
        self.assertEqual(strip_emoji('<span class="x">📝 Log</span>'), '<span class="x">Log</span>')

    def test_page_titles_render_without_emoji(self):
        out = Template(
            "{% load scene_tags %}{% filter strip_emoji %}🌴 Time off{% endfilter %}"
        ).render(Context())
        self.assertEqual(out, "Time off")

    def test_icons(self):
        html = icon("pencil")
        self.assertIn('class="icon"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn(PATHS["pencil"], html)
        self.assertIn('class="icon big"', icon("trash", "big"))
        with self.assertRaises(KeyError):
            icon("no-such-icon")


class BriefingTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Test Practice", slug="briefing-test")
        self.client_obj = Client.objects.create(
            practice=self.practice, client_code="AB-1", full_name="Anna Schmidt"
        )
        self.today = date(2026, 10, 1)
        self.now = timezone.make_aware(datetime(2026, 10, 1, 11, 0))

    def brief(self, stats=EMPTY_STATS):
        return build_briefing(self.practice, stats, self.today, self.now)

    def texts(self, briefing):
        return [item.text for item in briefing.items]

    def test_quiet_day(self):
        briefing = self.brief()
        self.assertEqual(self.texts(briefing), ["No sessions on the calendar today."])
        self.assertEqual(briefing.attention_count, 0)
        self.assertEqual(briefing.summary, "Everything is in order. Enjoy the quiet.")

    def test_next_session_names_the_code_not_the_client(self):
        Session.objects.create(
            client=self.client_obj, session_date=self.today, session_time=time(9)
        )
        Session.objects.create(
            client=self.client_obj, session_date=self.today, session_time=time(14)
        )
        Session.objects.create(
            client=self.client_obj, session_date=self.today, session_time=time(16), cancelled=True
        )
        text = self.texts(self.brief())[0]
        self.assertEqual(text, "2 sessions today. Next at 2:00 PM with AB-1.")
        self.assertNotIn("Anna", text)

    def test_sessions_all_done(self):
        Session.objects.create(
            client=self.client_obj, session_date=self.today, session_time=time(8)
        )
        self.assertEqual(self.texts(self.brief())[0], "1 session today, and it's behind you.")

    def test_attention_items(self):
        PracticeTodo.objects.create(
            practice=self.practice,
            title="Call back",
            category="admin",
            priority="medium",
            due_date=self.today,
        )
        PracticeTodo.objects.create(
            practice=self.practice,
            title="Snoozed",
            category="admin",
            priority="medium",
            due_date=self.today,
            snoozed_until=self.today + timedelta(days=2),
        )
        ClientDocument.objects.create(
            client=self.client_obj,
            file="client_documents/consent.pdf",
            uploaded_via_portal=True,
        )
        ProviderLicense.objects.create(
            practice=self.practice,
            state="VA",
            license_number="VA-1",
            expiration_date=timezone.localdate() + timedelta(days=30),
        )
        ClientInquiry.objects.create(
            practice=self.practice,
            full_name="Max Mustermann",
            source=InquirySource.WEBSITE,
            status=InquiryStatus.NEW,
            inquiry_date=self.today,
        )
        briefing = self.brief()
        texts = self.texts(briefing)
        self.assertIn("1 task is due in your focus queue.", texts)
        self.assertIn("A client sent 1 new document through the portal.", texts)
        self.assertTrue(any(t.startswith("Your Virginia license expires on") for t in texts))
        self.assertIn("1 new inquiry is waiting for a reply.", texts)
        self.assertEqual(briefing.attention_count, 4)
        self.assertEqual(briefing.summary, "4 things could use your attention.")
        self.assertNotIn("Max Mustermann", " ".join(texts))

    def test_expired_license(self):
        ProviderLicense.objects.create(
            practice=self.practice,
            state="NM",
            license_number="NM-1",
            expiration_date=timezone.localdate() - timedelta(days=1),
        )
        self.assertIn("Your New Mexico license has expired.", self.texts(self.brief()))

    def test_invoice_lines_come_from_the_status_breakdown(self):
        stats = dict(EMPTY_STATS)
        stats["draft"] = {"count": 3, "total": Decimal("300")}
        stats["sent"] = {"count": 2, "total": Decimal("1250.40")}
        texts = self.texts(self.brief(stats))
        self.assertIn("3 draft invoices are ready to send.", texts)
        self.assertIn("2 invoices are awaiting payment ($1,250).", texts)
        self.assertEqual(self.brief(stats).attention_count, 0)


class ShellRenderingTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Test Practice", slug="shell-test")
        self.user = User.objects.create_user(username="shelluser", password="testpass123")
        UserPractice.objects.create(user=self.user, practice=self.practice, is_owner=True)

    def login(self):
        self.client.login(username="shelluser", password="testpass123")

    def test_section_page_carries_its_scene_and_credit(self):
        self.login()
        response = self.client.get(reverse("client_list"))
        self.assertContains(response, 'data-scene="clients"')
        self.assertContains(response, "clients-ambient.webp")
        self.assertContains(response, SCENES["clients"].photographer)
        self.assertContains(response, 'class="mainnav__link is-active">Clients<')

    def test_dashboard_greets_and_briefs(self):
        self.login()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "scene--tall")
        self.assertContains(response, "Today at a glance")
        self.assertContains(response, "No sessions on the calendar today.")
        self.assertRegex(response.content.decode(), r'data-scene="(dawn|day|dusk|night)"')
        self.assertContains(response, "Good ")

    def test_sign_in_is_a_full_screen_scene_without_navigation(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "scene--full")
        self.assertContains(response, "signin__card")
        self.assertNotContains(response, "mainnav")
        self.assertNotContains(response, 'class="page"')

    def test_time_of_day_scenes_carry_deferred_footage_and_both_credits(self):
        response = self.client.get(reverse("login"))
        html = response.content.decode()
        key = re.search(r'data-scene="(\w+)"', html).group(1)
        scene = SCENES[key]
        self.assertTrue(scene.video)
        self.assertContains(response, "scene--footage")
        self.assertContains(response, f'data-src="/static/scenes/{key}.mp4"')
        self.assertContains(response, scene.photographer)
        self.assertContains(response, scene.footage.source_url)
        self.assertIn("classList.add('motion-on')", html)

    def test_photo_only_scenes_have_no_footage_markup(self):
        self.login()
        response = self.client.get(reverse("focus_queue"))
        self.assertNotContains(response, "<video")
        self.assertNotContains(response, "scene--footage")
        self.assertNotContains(response, "scene__credit-footage")

    def test_page_titles_have_no_emoji(self):
        self.login()
        response = self.client.get(reverse("plaid_home"))
        title = re.search(r'<h1 class="scene__title">(.*?)</h1>', response.content.decode(), re.S)
        self.assertEqual(title.group(1).strip(), "Bank connection")

    def test_not_found_page(self):
        request = RequestFactory().get("/nowhere/")
        request.user = AnonymousUser()
        html = render_to_string("404.html", request=request)
        self.assertIn('data-scene="notfound"', html)
        self.assertIn("This path leads nowhere.", html)
        self.assertNotIn("Back to your overview", html)

    def test_server_error_page_needs_no_context(self):
        html = render_to_string("500.html")
        self.assertIn('data-scene="dusk"', html)
        self.assertIn("Let's take a breath.", html)
