"""Tests for professional license tracking (state licensure for LPC practice)."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client as TestClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Client, Practice, PracticeTodo, ProviderLicense, UserPractice
from ..utils.licensure import client_licensure_gap, licensed_states, licenses_needing_attention


class LicensureTestBase(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Test Practice", slug="licensure-test")
        self.today = timezone.localdate()

    def license(self, state, expires_in_days=None):
        return ProviderLicense.objects.create(
            practice=self.practice,
            state=state,
            license_number=f"{state}-1",
            expiration_date=(
                self.today + timedelta(days=expires_in_days)
                if expires_in_days is not None
                else None
            ),
        )


class ProviderLicenseModelTest(LicensureTestBase):
    def test_no_expiration_date_is_current(self):
        lic = self.license("TX")
        self.assertTrue(lic.is_current())
        self.assertFalse(lic.expires_soon)

    def test_expired(self):
        lic = self.license("TX", expires_in_days=-1)
        self.assertTrue(lic.is_expired)
        self.assertFalse(lic.expires_soon)

    def test_expires_on_its_last_day(self):
        self.assertTrue(self.license("TX", expires_in_days=0).is_current())

    def test_expires_soon_within_90_days(self):
        self.assertTrue(self.license("TX", expires_in_days=90).expires_soon)
        self.assertFalse(self.license("UT", expires_in_days=91).expires_soon)

    def test_str(self):
        self.assertEqual(str(self.license("NM")), "LPC NM #NM-1")


class LicensureHelpersTest(LicensureTestBase):
    def test_licensed_states_excludes_expired(self):
        self.license("TX")
        self.license("VA", expires_in_days=-10)
        self.assertEqual(licensed_states(self.practice), {"TX"})

    def test_client_gap(self):
        self.license("TX")
        in_state = Client.objects.create(
            practice=self.practice, client_code="AB-1", full_name="Anna Schmidt", state="TX"
        )
        out_of_state = Client.objects.create(
            practice=self.practice, client_code="CD-2", full_name="Max Mustermann", state="OK"
        )
        unknown = Client.objects.create(
            practice=self.practice, client_code="EF-3", full_name="Maria Musterfrau"
        )
        self.assertIsNone(client_licensure_gap(in_state))
        self.assertEqual(client_licensure_gap(out_of_state), "OK")
        self.assertIsNone(client_licensure_gap(unknown))

    def test_licenses_needing_attention(self):
        self.license("TX", expires_in_days=400)
        soon = self.license("UT", expires_in_days=30)
        expired = self.license("VA", expires_in_days=-5)
        self.license("NM")
        self.assertEqual(set(licenses_needing_attention(self.practice)), {soon, expired})


class LicenseRenewalSyncTest(LicensureTestBase):
    def test_creates_and_closes_renewal_task(self):
        lic = self.license("VA", expires_in_days=30)
        call_command("sync_focus_queue_tasks", verbosity=0)

        task = PracticeTodo.objects.get(task_type=PracticeTodo.TaskType.LICENSE_RENEWAL)
        self.assertIsNone(task.completed_at)
        self.assertEqual(task.due_date, lic.expiration_date)
        self.assertEqual(task.related_object_url, reverse("license_list"))

        # Renewing pushes the expiration out of the warning window → task closes
        lic.expiration_date = self.today + timedelta(days=730)
        lic.save()
        call_command("sync_focus_queue_tasks", verbosity=0)
        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)


class LicenseViewsTest(LicensureTestBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="licuser", password="testpass123")
        UserPractice.objects.create(user=self.user, practice=self.practice, is_owner=True)
        self.http = TestClient()
        self.http.login(username="licuser", password="testpass123")
        session = self.http.session
        session["current_practice_slug"] = self.practice.slug
        session.save()

    def _management(self, total, initial):
        return {
            "licenses-TOTAL_FORMS": str(total),
            "licenses-INITIAL_FORMS": str(initial),
            "licenses-MIN_NUM_FORMS": "0",
            "licenses-MAX_NUM_FORMS": "1000",
        }

    def test_page_loads(self):
        self.license("TX", expires_in_days=30)
        response = self.http.get(reverse("license_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LPC TX #TX-1")
        self.assertContains(response, "Expires")

    def test_add_licenses(self):
        data = self._management(1, 0) | {
            "licenses-0-state": "UT",
            "licenses-0-license_type": "LPC",
            "licenses-0-license_number": "UT-12345",
            "licenses-0-expiration_date": "2027-03-31",
            "licenses-0-notes": "",
        }
        response = self.http.post(reverse("license_list"), data)
        self.assertRedirects(response, reverse("license_list"))
        lic = ProviderLicense.objects.get(practice=self.practice)
        self.assertEqual((lic.state, lic.license_number), ("UT", "UT-12345"))

    def test_duplicate_state_and_type_rejected(self):
        self.license("TX")
        existing = ProviderLicense.objects.get()
        data = self._management(2, 1) | {
            "licenses-0-id": str(existing.pk),
            "licenses-0-state": "TX",
            "licenses-0-license_type": "LPC",
            "licenses-0-license_number": "TX-1",
            "licenses-0-expiration_date": "",
            "licenses-0-notes": "",
            "licenses-1-state": "TX",
            "licenses-1-license_type": "LPC",
            "licenses-1-license_number": "TX-2",
            "licenses-1-expiration_date": "",
            "licenses-1-notes": "",
        }
        response = self.http.post(reverse("license_list"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProviderLicense.objects.count(), 1)

    def test_client_detail_warns_about_unlicensed_state(self):
        self.license("TX")
        client = Client.objects.create(
            practice=self.practice, client_code="CD-2", full_name="Max Mustermann", state="OK"
        )
        response = self.http.get(reverse("client_detail", kwargs={"pk": client.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No current license for OK")

    def test_client_detail_no_warning_when_licensed(self):
        self.license("TX")
        client = Client.objects.create(
            practice=self.practice, client_code="AB-1", full_name="Anna Schmidt", state="TX"
        )
        response = self.http.get(reverse("client_detail", kwargs={"pk": client.pk}))
        self.assertNotContains(response, "No current license")
