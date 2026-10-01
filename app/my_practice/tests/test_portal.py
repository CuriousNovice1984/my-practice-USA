"""Tests for the client forms portal (public upload links + staff management)."""

import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client as TestClient
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import Client, ClientDocument, Practice, PracticeTodo, UserPractice
from ..models.portal import MAX_UPLOADS_PER_LINK, PortalLink, PracticeForm, hash_token

TEST_FERNET_KEY = "7zIJPIlZkdMSPifNsPuNBjIAIqiUkFHmRJN8HGG8ytQ="  # gitleaks:allow
MEDIA_ROOT = tempfile.mkdtemp(prefix="portal-test-media-")

# Smallest valid PNG (1×1) — goes through the real image pipeline in process_upload
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def png(name="consent.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


@override_settings(FERNET_KEY=TEST_FERNET_KEY, MEDIA_ROOT=MEDIA_ROOT)
class PortalTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.practice = Practice.objects.create(name="Test Practice", slug="portal-test")
        self.client_obj = Client.objects.create(
            practice=self.practice,
            client_code="AB-1",
            full_name="Anna Schmidt",
            email="anna@example.com",
        )
        self.consent_form = PracticeForm.objects.create(
            practice=self.practice,
            title="Informed consent",
            document_type=ClientDocument.DocumentType.CONSENT,
            file=SimpleUploadedFile(
                "consent.pdf", b"%PDF-1.4 blank", content_type="application/pdf"
            ),
        )
        self.anon = TestClient()

    def make_link(self, days=14):
        return PortalLink.create_for(self.client_obj, days)


class PortalLinkModelTest(PortalTestBase):
    def test_token_is_hashed_for_lookup_and_encrypted_at_rest(self):
        link = self.make_link()
        self.assertEqual(link.token_hash, hash_token(link.token))
        self.assertGreaterEqual(len(link.token), 40)
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT token FROM my_practice_portallink WHERE id = %s", [link.pk])
            self.assertNotIn(link.token, cursor.fetchone()[0])

    def test_find_active(self):
        link = self.make_link()
        self.assertEqual(PortalLink.find_active(link.token), link)
        self.assertIsNone(PortalLink.find_active("not-a-token"))

    def test_expired_and_revoked_links_are_inactive(self):
        expired = self.make_link()
        expired.expires_at = timezone.now() - timedelta(minutes=1)
        expired.save()
        revoked = self.make_link()
        revoked.revoked_at = timezone.now()
        revoked.save()
        self.assertIsNone(PortalLink.find_active(expired.token))
        self.assertIsNone(PortalLink.find_active(revoked.token))


class PublicPortalTest(PortalTestBase):
    def test_page_loads_without_login_and_hides_client_identity(self):
        link = self.make_link()
        response = self.anon.get(reverse("portal_home", args=[link.token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secure document upload for Test Practice")
        self.assertContains(response, "Informed consent")
        self.assertNotContains(response, "Anna Schmidt")
        self.assertNotContains(response, "anna@example.com")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_page_has_no_staff_navigation(self):
        link = self.make_link()
        response = self.anon.get(reverse("portal_home", args=[link.token]))
        self.assertNotContains(response, reverse("client_list"))
        self.assertNotContains(response, "cmd-palette")

    def test_unknown_or_expired_link_is_404(self):
        response = self.anon.get(reverse("portal_home", args=["bogus-token"]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "no longer available", status_code=404)

    def test_download_blank_form(self):
        link = self.make_link()
        response = self.anon.get(
            reverse("portal_form_download", args=[link.token, self.consent_form.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

    def test_cannot_download_another_practices_form(self):
        other = Practice.objects.create(name="Other", slug="portal-other")
        foreign = PracticeForm.objects.create(
            practice=other,
            title="Other form",
            file=SimpleUploadedFile("x.pdf", b"%PDF-1.4", content_type="application/pdf"),
        )
        link = self.make_link()
        response = self.anon.get(reverse("portal_form_download", args=[link.token, foreign.pk]))
        self.assertEqual(response.status_code, 404)

    def test_upload_files_as_selected_form_type(self):
        link = self.make_link()
        response = self.anon.post(
            reverse("portal_home", args=[link.token]),
            {"form": self.consent_form.pk, "files": [png("p1.png"), png("p2.png")]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "your documents were received")
        docs = ClientDocument.objects.filter(client=self.client_obj)
        self.assertEqual(docs.count(), 2)
        for doc in docs:
            self.assertTrue(doc.uploaded_via_portal)
            self.assertIsNone(doc.reviewed_at)
            self.assertEqual(doc.document_type, ClientDocument.DocumentType.CONSENT)
        link.refresh_from_db()
        self.assertEqual(link.upload_count, 2)
        self.assertIsNotNone(link.last_used_at)

    def test_upload_completes_onboarding_step(self):
        link = self.make_link()
        self.anon.post(
            reverse("portal_home", args=[link.token]),
            {"form": self.consent_form.pk, "files": [png()]},
        )
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.contract_signed_date, timezone.localdate())

    def test_disallowed_file_type_rejected(self):
        link = self.make_link()
        response = self.anon.post(
            reverse("portal_home", args=[link.token]),
            {"files": [SimpleUploadedFile("evil.html", b"<script>", content_type="text/html")]},
        )
        self.assertContains(response, "not allowed")
        self.assertFalse(ClientDocument.objects.exists())

    def test_upload_limit_per_link(self):
        link = self.make_link()
        link.upload_count = MAX_UPLOADS_PER_LINK
        link.save()
        response = self.anon.post(reverse("portal_home", args=[link.token]), {"files": [png()]})
        self.assertFalse(ClientDocument.objects.exists())
        self.assertContains(response, "upload limit")

    def test_expired_link_rejects_upload(self):
        link = self.make_link()
        link.expires_at = timezone.now() - timedelta(seconds=1)
        link.save()
        response = self.anon.post(reverse("portal_home", args=[link.token]), {"files": [png()]})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ClientDocument.objects.exists())


class StaffPortalTest(PortalTestBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="portaluser", password="testpass123")
        UserPractice.objects.create(user=self.user, practice=self.practice, is_owner=True)
        self.http = TestClient()
        self.http.login(username="portaluser", password="testpass123")
        session = self.http.session
        session["current_practice_slug"] = self.practice.slug
        session.save()

    def test_create_link_and_show_on_client_page(self):
        response = self.http.post(
            reverse("portal_link_create", args=[self.client_obj.pk]), {"days": "7"}
        )
        self.assertEqual(response.status_code, 302)
        link = PortalLink.objects.get(client=self.client_obj)
        self.assertAlmostEqual(
            (link.expires_at - timezone.now()).total_seconds(), 7 * 86400, delta=60
        )
        detail = self.http.get(reverse("client_detail", args=[self.client_obj.pk]))
        self.assertContains(detail, reverse("portal_home", args=[link.token]))

    @override_settings(PORTAL_BASE_URL="https://practice-box.example-tailnet.ts.net")
    def test_link_uses_public_base_url(self):
        link = self.make_link()
        detail = self.http.get(reverse("client_detail", args=[self.client_obj.pk]))
        self.assertContains(
            detail,
            "https://practice-box.example-tailnet.ts.net"
            + reverse("portal_home", args=[link.token]),
        )

    def test_revoke(self):
        link = self.make_link()
        self.http.post(reverse("portal_link_revoke", args=[link.pk]))
        link.refresh_from_db()
        self.assertIsNotNone(link.revoked_at)
        self.assertIsNone(PortalLink.find_active(link.token))

    def test_email_link(self):
        link = self.make_link()
        url = reverse("send_portal_link_email", args=[self.client_obj.pk])
        response = self.http.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.context["form"].initial["body"]
        self.assertIn(reverse("portal_home", args=[link.token]), body)
        self.http.post(url, {"recipient": "anna@example.com", "subject": "Forms", "body": body})
        self.assertEqual(len(mail.outbox), 1)

    def test_email_requires_an_active_link(self):
        response = self.http.get(reverse("send_portal_link_email", args=[self.client_obj.pk]))
        self.assertRedirects(response, reverse("client_detail", args=[self.client_obj.pk]))

    def test_manage_forms(self):
        response = self.http.post(
            reverse("portal_forms"),
            {
                "title": "Intake packet",
                "description": "",
                "document_type": ClientDocument.DocumentType.INTAKE,
                "sort_order": "1",
                "file": SimpleUploadedFile(
                    "intake.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
            },
        )
        self.assertRedirects(response, reverse("portal_forms"))
        new_form = PracticeForm.objects.get(title="Intake packet")
        self.http.post(reverse("portal_form_toggle", args=[new_form.pk]))
        new_form.refresh_from_db()
        self.assertFalse(new_form.active)
        self.http.post(reverse("portal_form_delete", args=[new_form.pk]))
        self.assertFalse(PracticeForm.objects.filter(pk=new_form.pk).exists())

    def test_blank_form_must_be_pdf_or_docx(self):
        response = self.http.post(
            reverse("portal_forms"),
            {
                "title": "Bad",
                "document_type": ClientDocument.DocumentType.OTHER,
                "sort_order": "0",
                "file": SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PracticeForm.objects.filter(title="Bad").exists())

    def test_review_uploads_and_focus_queue(self):
        link = self.make_link()
        self.anon.post(reverse("portal_home", args=[link.token]), {"files": [png()]})
        call_command("sync_focus_queue_tasks", verbosity=0)
        task = PracticeTodo.objects.get(task_type=PracticeTodo.TaskType.PORTAL_UPLOADS)
        self.assertEqual(task.title, "1 client uploads to review")
        self.assertEqual(task.related_object_url, reverse("portal_uploads"))

        doc = ClientDocument.objects.get()
        page = self.http.get(reverse("portal_uploads"))
        self.assertContains(page, "AB-1")
        self.assertNotContains(page, "Anna Schmidt")
        self.http.post(reverse("portal_upload_mark_reviewed", args=[doc.pk]))
        doc.refresh_from_db()
        self.assertIsNotNone(doc.reviewed_at)

        call_command("sync_focus_queue_tasks", verbosity=0)
        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)

    def test_staff_pages_require_login(self):
        for name in ("portal_forms", "portal_uploads"):
            response = self.anon.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("login", response["Location"])


class FunnelPathGuardTest(PortalTestBase):
    """Requests proxied from the internet by Tailscale Funnel only reach the portal."""

    def test_funnel_request_to_portal_allowed(self):
        link = self.make_link()
        response = self.anon.get(
            reverse("portal_home", args=[link.token]), HTTP_TAILSCALE_FUNNEL_REQUEST="?1"
        )
        self.assertEqual(response.status_code, 200)

    def test_funnel_request_to_app_refused(self):
        for path in (reverse("login"), reverse("client_list"), "/admin/"):
            response = self.anon.get(path, HTTP_TAILSCALE_FUNNEL_REQUEST="?1")
            self.assertEqual(response.status_code, 404, path)

    def test_tailnet_request_unaffected(self):
        response = self.anon.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
