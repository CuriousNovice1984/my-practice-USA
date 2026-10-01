"""Bank connection via Plaid: link accounts, sync transactions into bank review."""

import json
import logging

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..models.plaid import PlaidAccount, PlaidItem
from ..utils.plaid_client import PlaidClient, PlaidError, plaid_configured
from ..utils.plaid_sync import link_item, sync_practice
from ..utils.practice_helpers import require_practice

logger = logging.getLogger(__name__)


@require_practice
def plaid_home(request: HttpRequest) -> HttpResponse:
    """Landing page: linked banks, their accounts, and the connect/sync actions."""
    items = (
        PlaidItem.objects.for_current_practice(request)
        .prefetch_related("accounts")
        .order_by("institution_name")
    )
    return render(
        request,
        "my_practice/plaid_home.html",
        {"items": items, "plaid_configured": plaid_configured()},
    )


@require_practice
@require_POST
def plaid_link_token(request: HttpRequest) -> JsonResponse:
    """Create a short-lived Link token for the browser to open Plaid Link with."""
    try:
        token = PlaidClient().create_link_token(user_id=str(request.user.pk))
    except PlaidError as exc:
        logger.warning("Plaid link token failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({"link_token": token})


@require_practice
@require_POST
def plaid_exchange(request: HttpRequest) -> JsonResponse:
    """Store the bank Plaid Link just connected (public token → access token)."""
    try:
        payload = json.loads(request.body)
        public_token = payload["public_token"]
    except ValueError, KeyError:
        return JsonResponse({"error": _("Invalid request")}, status=400)
    institution = (payload.get("institution") or {}).get("name") or ""
    try:
        item = link_item(request.current_practice, public_token, institution)
    except PlaidError as exc:
        logger.warning("Plaid token exchange failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)
    messages.success(
        request,
        _("Connected %(bank)s. Choose which accounts to import, then sync.") % {"bank": item},
    )
    return JsonResponse({"ok": True})


@require_practice
@require_POST
def plaid_sync(request: HttpRequest) -> HttpResponse:
    """Import new transactions from every linked bank, then go to the review page."""
    try:
        results = sync_practice(request.current_practice)
    except PlaidError as exc:
        messages.error(request, _("Bank sync failed: %(error)s") % {"error": exc})
        return redirect("plaid_home")
    for error in results["errors"]:
        messages.error(request, error)
    messages.success(
        request,
        _(
            "Bank sync: %(total)s new transactions — %(matched)s matched to invoices, "
            "%(unmatched)s to review, %(review)s expenses or withdrawals detected."
        )
        % {
            "total": results["total"] - results["ignored"],
            "matched": results["matched"],
            "unmatched": results["unmatched"],
            "review": results["needs_review"],
        },
    )
    return redirect("bank_review")


@require_practice
@require_POST
def plaid_toggle_account(request: HttpRequest, pk: int) -> HttpResponse:
    """Switch transaction import on or off for one account."""
    account = get_object_or_404(PlaidAccount, pk=pk, item__practice=request.current_practice)
    account.import_enabled = not account.import_enabled
    account.save(update_fields=["import_enabled"])
    return redirect("plaid_home")


@require_practice
@require_POST
def plaid_remove(request: HttpRequest, pk: int) -> HttpResponse:
    """Disconnect a bank: revoke the token at Plaid, then forget it locally.

    Already-imported transactions stay — they are the practice's records.
    """
    item = get_object_or_404(PlaidItem.objects.for_current_practice(request), pk=pk)
    try:
        PlaidClient().remove_item(item.access_token)
    except PlaidError as exc:
        # Still remove locally: the user asked to disconnect, and a token Plaid
        # already considers invalid can't be revoked twice.
        logger.warning("Plaid item removal failed for %s: %s", item.item_id, exc)
    name = str(item)
    item.delete()
    messages.success(request, _("Disconnected %(bank)s.") % {"bank": name})
    return redirect("plaid_home")
