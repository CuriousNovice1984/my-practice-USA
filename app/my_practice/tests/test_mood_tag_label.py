"""
Tests for the mood_tag_label filter.

SessionLog.mood_tags stores raw MoodTag keys as a JSON list, so get_FOO_display()
is unavailable and templates used to print the key directly ({{ tag|title }}).
That rendered "Hohe_Aktivierung" in the UI — invisible to the i18n guardrail,
which only scans template source for literal German. The UI is English-only
now (no locale catalogs), so the label must be the English one.
"""

from django.template import Context, Template
from django.test import TestCase
from django.utils import translation

from ..models.clinical import MoodTag


class MoodTagLabelFilterTests(TestCase):
    def _render(self, value: str, language: str) -> str:
        template = Template("{% load payment_tags %}{{ tag|mood_tag_label }}")
        with translation.override(language):
            return template.render(Context({"tag": value})).strip()

    def test_renders_the_english_label(self):
        """The whole point of the filter: a readable label, not the storage key."""
        self.assertEqual(self._render(MoodTag.HOHE_AKTIVIERUNG.value, "en"), "High activation")

    def test_never_leaks_the_storage_key(self):
        """No locale may surface the raw underscore-separated key."""
        for language in ("de", "en"):
            for tag in MoodTag:
                rendered = self._render(tag.value, language)
                self.assertNotIn("_", rendered, f"{tag.value} leaked its key in {language}")

    def test_unknown_key_degrades_gracefully(self):
        """Keys retired from MoodTag still sit in old JSON rows — render, don't crash."""
        self.assertEqual(self._render("legacy_tag", "en"), "Legacy tag")
        self.assertEqual(self._render("", "en"), "")
