"""Admin configuration for Practice."""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from ..models import Practice


@admin.register(Practice)
class PracticeAdmin(admin.ModelAdmin):
    """Practice admin with field groups for better organization (Django 5.1 feature)"""

    fieldsets = (
        (
            gettext_lazy("Basic Information"),
            {
                "fields": (
                    "name",
                    "short_title",
                    "title",
                    "subtitle",
                ),
                "description": gettext_lazy("Basic information about the practice"),
            },
        ),
        (
            gettext_lazy("Address"),
            {
                "fields": ("street", "city", "state", "postal_code", "country"),
                "classes": ("collapse",),  # Collapsible group
            },
        ),
        (
            gettext_lazy("Contact"),
            {
                "fields": ("email", "email_from_name", "website", "phone"),
                "classes": ("collapse",),
            },
        ),
        (
            gettext_lazy("Payments"),
            {
                "fields": ("payment_instructions", "private_bank_account"),
                "classes": ("collapse",),
                "description": gettext_lazy(
                    "Payment instructions are printed on invoices. The private bank account "
                    "is used during bank import to automatically detect owner draws and "
                    "contributions."
                ),
            },
        ),
        (
            gettext_lazy("Bank Import (CSV format)"),
            {
                "fields": (
                    "csv_delimiter",
                    "csv_column_date",
                    "csv_column_value_date",
                    "csv_column_payer_name",
                    "csv_column_payer_account",
                    "csv_column_reference",
                    "csv_column_amount",
                    "csv_column_balance",
                    "csv_column_account",
                ),
                "classes": ("collapse",),
                "description": gettext_lazy(
                    "Delimiter and column names for your bank's CSV export, used by "
                    "/bank/import. Adjust to match your bank's export."
                ),
            },
        ),
        (
            gettext_lazy("Tax"),
            {
                "fields": ("tax_id", "records_retention_years"),
                "classes": ("collapse",),
            },
        ),
        (
            gettext_lazy("Memberships"),
            {
                "fields": ("professional_memberships",),
                "classes": ("collapse",),
            },
        ),
        (
            gettext_lazy("Images"),
            {
                "fields": (
                    "logo",
                    "logo_preview",
                    "signature",
                    "signature_preview",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            gettext_lazy("Payment Terms"),
            {
                "fields": (
                    "payment_terms_days",
                    "payment_terms_text",
                    "overdue_after_days",
                ),
                "classes": ("collapse",),
                "description": gettext_lazy(
                    "'Overdue after' controls when the dashboard, Focus Queue, and client "
                    "payment-reminder button treat a sent invoice as overdue."
                ),
            },
        ),
        (
            gettext_lazy("Email Templates for Invoices"),
            {
                "fields": (
                    "invoice_email_subject",
                    "invoice_email_body",
                    "email_signature",
                ),
                "classes": ("collapse", "wide"),  # Collapsible + wide for text fields
                "description": gettext_lazy(
                    "Templates for invoice emails. Available placeholders: {salutation}, "
                    "{invoice_number}, {amount}, {date}, {client_name}"
                ),
            },
        ),
        (
            gettext_lazy("Capacity Monitoring (P-013)"),
            {
                "fields": (
                    "monthly_target_hours",
                    "monthly_target_revenue",
                ),
                "classes": ("collapse",),
                "description": gettext_lazy(
                    "Monthly targets for hours and revenue. When set, the dashboard shows "
                    "warnings for declining numbers."
                ),
            },
        ),
        (
            gettext_lazy("Home Office"),
            {
                "fields": ("home_office_sqft",),
                "classes": ("collapse",),
                "description": gettext_lazy(
                    "Used for the simplified home office deduction on the tax year summary."
                ),
            },
        ),
    )

    readonly_fields = ["logo_preview", "signature_preview"]

    @admin.display(description=gettext_lazy("Logo Preview"))
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="max-height: 200px;"/>', obj.logo.url)
        return _("No logo uploaded")

    @admin.display(description=gettext_lazy("Signature Preview"))
    def signature_preview(self, obj):
        if obj.signature:
            return format_html('<img src="{}" style="max-height: 100px;"/>', obj.signature.url)
        return _("No signature uploaded")

    def has_add_permission(self, request):
        # Only allow one Practice instance
        return not Practice.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion
        return False
