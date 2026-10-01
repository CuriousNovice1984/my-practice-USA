"""
Interactive first-run wizard: creates a Practice and assigns it to all superusers.

Prompts for the fields needed to generate invoices (name, address, bank details,
tax status). Everything else (logo, signature, email templates, targets) can be
configured later via the Django admin.

Usage:
    ./dev.py manage setup_practice
    ./dev.py manage setup_practice --no-input  # non-interactive, uses defaults (testing only)
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from ...models import Practice, UserPractice


class Command(BaseCommand):
    help = "Interactive wizard to create your practice and link it to your account"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip prompts and use blank defaults (for automated testing)",
        )

    def handle(self, *args, **options) -> None:
        no_input = options["no_input"]

        self.stdout.write("\n" + self.style.SUCCESS("my-practice setup") + "\n")
        self.stdout.write(
            "This creates your practice and links it to your superuser account.\n"
            "You can edit everything later in the Django admin.\n\n"
        )

        name = self._ask("Your name (appears on invoices)", "Anna Mustermann", no_input)
        default_slug = slugify(name)
        slug = self._ask("Practice slug (used in URLs)", default_slug, no_input)

        if Practice.objects.filter(slug=slug).exists():
            raise CommandError(
                f"A practice with slug '{slug}' already exists. "
                "Choose a different slug or edit the existing practice in the admin."
            )

        title = self._ask(
            "Professional title",
            "Licensed Professional Counselor (LPC)",
            no_input,
        )
        short_title = self._ask("Short title (for the title bar)", "Therapy", no_input)

        self.stdout.write("\nAddress (appears on invoices):")
        street = self._ask("  Street", "", no_input)
        city = self._ask("  City", "", no_input)
        state = self._ask("  State (two-letter code)", "TX", no_input).upper()
        postal_code = self._ask("  ZIP code", "", no_input)

        self.stdout.write("\nContact:")
        email = self._ask("  Email", "mail@example.com", no_input)

        self.stdout.write("\nPayments (printed on invoices):")
        payment_instructions = self._ask(
            "  Payment instructions (e.g. 'Zelle: payments@practice.example')", "", no_input
        )

        self.stdout.write("\nTax:")
        tax_id = self._ask("  EIN", "", no_input)

        practice = Practice.objects.create(
            name=name,
            slug=slug,
            title=title,
            short_title=short_title,
            street=street,
            city=city,
            state=state,
            postal_code=postal_code,
            email=email,
            payment_instructions=payment_instructions,
            tax_id=tax_id,
        )

        User = get_user_model()
        assigned = []
        for user in User.objects.filter(is_superuser=True):
            UserPractice.objects.get_or_create(
                user=user,
                practice=practice,
                defaults={"is_owner": True},
            )
            assigned.append(user.username)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f'✅ Created practice "{name}" (slug: {slug})'))
        if assigned:
            self.stdout.write(f"   Assigned to: {', '.join(assigned)}")
        self.stdout.write("")
        self.stdout.write("Next steps:")
        self.stdout.write("  • Open http://localhost:8000 and log in")
        self.stdout.write(
            f"  • Add logo, signature, and email templates in the admin:\n"
            f"    http://localhost:8000/admin/my_practice/practice/{practice.pk}/change/"
        )
        self.stdout.write("  • Add your first client and start logging sessions")
        self.stdout.write("")

    def _ask(self, label: str, default: str, no_input: bool) -> str:
        if no_input:
            return default
        display_default = f" [{default}]" if default else ""
        value = input(f"{label}{display_default}: ").strip()
        return value if value else default
