"""Import new bank transactions for every practice with a Plaid connection.

Run on a schedule (e.g. a daily systemd timer alongside sync_focus_queue_tasks)
or manually; the Bank connection page has the same action as a button.
"""

from django.core.management.base import BaseCommand, CommandError

from ...models import Practice
from ...models.plaid import PlaidItem
from ...utils.plaid_client import plaid_configured
from ...utils.plaid_sync import sync_practice


class Command(BaseCommand):
    help = "Sync bank transactions from Plaid into bank review for all practices."

    def handle(self, *args, **options):
        if not plaid_configured():
            raise CommandError("Plaid is not configured: set PLAID_CLIENT_ID and PLAID_SECRET.")
        practice_ids = PlaidItem.objects.values_list("practice_id", flat=True).distinct()
        failed = False
        for practice in Practice.objects.filter(pk__in=practice_ids, is_active=True):
            results = sync_practice(practice)
            new = results["total"] - results["ignored"]
            self.stdout.write(
                f"{practice.slug}: {new} new, {results['matched']} matched, "
                f"{results['unmatched']} to review, {results['needs_review']} auto-categorized"
            )
            for error in results["errors"]:
                failed = True
                self.stderr.write(f"  {error}")
        if failed:
            raise CommandError("One or more bank connections failed to sync.")
