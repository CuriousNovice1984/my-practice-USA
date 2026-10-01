"""Professional license management (states the practitioner is licensed in)."""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from ..forms import ProviderLicenseFormSet
from ..utils.practice_helpers import require_practice


@require_practice
def license_list(request: HttpRequest) -> HttpResponse:
    """List and edit the current practice's state licenses in one formset."""
    practice = request.current_practice
    if request.method == "POST":
        formset = ProviderLicenseFormSet(request.POST, instance=practice)
        if formset.is_valid():
            formset.save()
            messages.success(request, _("Licenses saved."))
            return redirect("license_list")
        messages.error(request, _("Please correct the errors below."))
    else:
        formset = ProviderLicenseFormSet(instance=practice)
    return render(request, "my_practice/license_list.html", {"formset": formset})
