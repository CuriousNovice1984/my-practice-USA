"""
Forms for the payments application.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import (
    CapacityPeriod,
    Client,
    CompanyExpense,
    CompanyWithdrawal,
    Practice,
    PracticeForm,
    ProviderLicense,
    TaxYearNote,
    TimeOff,
)


class DateFormField(forms.DateField):
    """DateField with standard HTML5 date input — use in ModelForm declarations."""

    def __init__(self, **kwargs):
        kwargs.setdefault("widget", forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
        kwargs.setdefault("input_formats", ["%Y-%m-%d"])
        super().__init__(**kwargs)


class StyledFormMixin:
    """
    Auto-applies CSS classes to all form widgets.

    Eliminates the need for attrs={"class": "form-control"} in every widget
    definition. CheckboxInput gets 'form-check-input'; everything else gets
    'form-control'.

    Usage:
        class MyForm(StyledFormMixin, forms.ModelForm):
            class Meta:
                model = MyModel
                fields = [...]
                widgets = {
                    # Only specify non-class attrs (type, step, rows, placeholder…)
                    "amount": forms.NumberInput(attrs={"step": "0.01"}),
                }
    """

    WIDGET_CLASSES: dict[type, str] = {
        forms.CheckboxInput: "form-check-input",
        forms.CheckboxSelectMultiple: "form-check-input",
    }
    DEFAULT_CLASS = "form-control"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = self.WIDGET_CLASSES.get(type(field.widget), self.DEFAULT_CLASS)
            existing = field.widget.attrs.get("class", "")
            if css not in existing:
                field.widget.attrs["class"] = f"{existing} {css}".strip()


class ClientIntakeForm(StyledFormMixin, forms.ModelForm):
    """Client intake form"""

    # Fields that only make sense for an individual therapy/coaching client,
    # not a company counterparty billed via free-form invoice items (P-122)
    # — see __init__ below.
    THERAPY_ONLY_FIELDS = (
        "date_of_birth",
        "cost_carrier",
        "hourly_rate_60",
        "hourly_rate_90",
        "is_online_client",
        "salutation",
    )

    date_of_birth = DateFormField(required=False, label=_("Date of birth"))

    class Meta:
        model = Client
        fields = [
            "client_code",
            "full_name",
            "date_of_birth",
            "email",
            "phone",
            "address",
            "state",
            "cost_carrier",
            "salutation",
            "active",
            "is_online_client",
            "hourly_rate_60",
            "hourly_rate_90",
            "notes",
        ]
        widgets = {
            "client_code": forms.TextInput(attrs={"placeholder": _("e.g. DE, JM"), "maxlength": 3}),
            "full_name": forms.TextInput(attrs={"placeholder": _("Full name")}),
            "email": forms.EmailInput(attrs={"placeholder": "email@example.com"}),
            "phone": forms.TextInput(attrs={"placeholder": "+1 ..."}),
            "address": forms.Textarea(
                attrs={"rows": 3, "placeholder": _("Street, City, State ZIP")}
            ),
            "cost_carrier": forms.TextInput(
                attrs={"placeholder": _("e.g. self-pay, HSA/FSA card")}
            ),
            "salutation": forms.TextInput(attrs={"placeholder": _('e.g., "Dear John"')}),
            "hourly_rate_60": forms.NumberInput(attrs={"step": "0.01"}),
            "hourly_rate_90": forms.NumberInput(attrs={"step": "0.01"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": _("Additional notes")}),
        }
        labels = {
            "client_code": _("Client code"),
            "full_name": _("Full name"),
            "email": _("Email"),
            "phone": _("Phone"),
            "address": _("Address"),
            "state": _("State (client location)"),
            "cost_carrier": _("Payment source"),
            "salutation": _("Custom Email Salutation"),
            "active": _("Active client"),
            "is_online_client": _("Online client (video sessions)"),
            "hourly_rate_60": _("Fee 60 min ($)"),
            "hourly_rate_90": _("Fee 90 min ($)"),
            "notes": _("Notes"),
        }

    def __init__(self, *args, **kwargs):
        """Hide therapy-only fields for free-form-items (P-122) practices —
        a company counterparty has no date of birth, insurance carrier, or
        per-session rate."""
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        practice = getattr(request, "current_practice", None) if request else None
        if practice and practice.allows_free_form_items:
            for field_name in self.THERAPY_ONLY_FIELDS:
                self.fields.pop(field_name, None)


class CompanyWithdrawalForm(StyledFormMixin, forms.ModelForm):
    """Form for creating and editing company withdrawals"""

    date = DateFormField(label=_("Date"))

    class Meta:
        model = CompanyWithdrawal
        fields = ["date", "amount", "category", "description"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": _("Optional: purpose or notes"),
                }
            ),
        }
        labels = {
            "amount": _("Amount ($)"),
            "category": _("Category"),
            "description": _("Description"),
        }


class CompanyExpenseForm(StyledFormMixin, forms.ModelForm):
    """Form for creating and editing company expenses"""

    date = DateFormField(label=_("Date"))

    class Meta:
        model = CompanyExpense
        fields = [
            "date",
            "description",
            "category",
            "amount",
            "is_tax_deductible",
            "has_invoice",
            "is_filed_in_tax_return",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": _("Description of the expense")}
            ),
            "amount": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
            "receipt": forms.ClearableFileInput(attrs={"accept": "application/pdf,image/*"}),
        }
        labels = {
            "description": _("Description"),
            "category": _("Category"),
            "amount": _("Amount ($)"),
            "is_tax_deductible": _("Tax deductible"),
            "has_invoice": _("Invoice available"),
            "is_filed_in_tax_return": _("Filed in tax return"),
        }


class TimeOffForm(StyledFormMixin, forms.ModelForm):
    """Form for creating and editing time-off periods"""

    start_date = DateFormField(label=_("Start Date"))
    end_date = DateFormField(label=_("End Date"))

    class Meta:
        model = TimeOff
        fields = ["start_date", "end_date", "type", "title", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "type": _("Type"),
            "title": _("Title"),
            "notes": _("Notes"),
        }


class PracticeEditForm(StyledFormMixin, forms.ModelForm):
    """Practice settings form."""

    class Meta:
        model = Practice
        fields = [
            "name",
            "short_title",
            "title",
            "subtitle",
            "street",
            "city",
            "state",
            "postal_code",
            "country",
            "email",
            "email_from_name",
            "website",
            "booking_url",
            "phone",
            "payment_instructions",
            "tax_id",
            "records_retention_years",
            "allows_free_form_items",
            "logo",
            "signature",
            "professional_memberships",
            "payment_terms_days",
            "payment_terms_text",
            "is_active",
            "home_office_sqft",
        ]
        widgets = {}


class CapacityPeriodForm(StyledFormMixin, forms.ModelForm):
    start_date = DateFormField(label=_("Valid from"))

    class Meta:
        model = CapacityPeriod
        fields = ["start_date", "hours_per_week"]


CapacityPeriodFormSet = forms.inlineformset_factory(
    Practice,
    CapacityPeriod,
    form=CapacityPeriodForm,
    extra=1,
    can_delete=True,
)


class ProviderLicenseForm(StyledFormMixin, forms.ModelForm):
    expiration_date = DateFormField(required=False, label=_("Expiration date"))

    class Meta:
        model = ProviderLicense
        fields = ["state", "license_type", "license_number", "expiration_date", "notes"]
        labels = {
            "state": _("State"),
            "license_type": _("License type"),
            "license_number": _("License number"),
            "notes": _("Notes"),
        }


ProviderLicenseFormSet = forms.inlineformset_factory(
    Practice,
    ProviderLicense,
    form=ProviderLicenseForm,
    extra=1,
    can_delete=True,
)


class TaxYearNoteForm(StyledFormMixin, forms.ModelForm):
    """Field-level validation for the save_tax_year_note AJAX endpoint.

    Two independent widgets share that endpoint (the allocation-note
    textarea on tax_year_summary.html, and the settlement amount/date
    fields on tax_quarter_overview.html), each POSTing only its own
    field(s) and expecting the other(s) left untouched. The view applies
    fields individually via .fields[name].clean(raw_value) rather than
    calling form.save(), so this form is never bound to the full instance
    or rendered — it exists to reuse Django's field parsing/validation
    instead of hand-rolled Decimal/date parsing.
    """

    settlement_amount = forms.DecimalField(
        required=False,
        localize=False,  # HTML5 <input type="number"> always sends "." as decimal separator
        max_digits=10,
        decimal_places=2,
        label=_("Tax back payment / refund"),
    )
    settlement_date = DateFormField(required=False, label=_("Assessment date"))

    class Meta:
        model = TaxYearNote
        fields = ["allocation_note", "settlement_amount", "settlement_date"]
        widgets = {
            "allocation_note": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "allocation_note": _("Allocation note"),
        }


class PracticeFormUploadForm(StyledFormMixin, forms.ModelForm):
    """Upload a blank form that clients download from the forms portal."""

    class Meta:
        model = PracticeForm
        fields = ["title", "description", "document_type", "file", "sort_order"]
        labels = {
            "title": _("Title"),
            "description": _("Instructions"),
            "document_type": _("Document type"),
            "file": _("File"),
            "sort_order": _("Order"),
        }

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload and not upload.name.lower().endswith((".pdf", ".docx")):
            raise forms.ValidationError(_("Upload blank forms as PDF or DOCX."))
        return upload
