"""
Middleware for development cache control, practice scoping and the public
portal boundary
"""

from django.http import Http404
from django.utils.deprecation import MiddlewareMixin

# The only paths reachable from the public internet (Tailscale Funnel)
PUBLIC_PATH_PREFIXES = ("/portal/", "/static/")


class FunnelPathGuardMiddleware:
    """
    Refuse anything but the client portal for requests arriving via Tailscale Funnel.

    Funnel marks the requests it proxies from the internet with a
    ``Tailscale-Funnel-Request`` header. The documented setup only mounts
    /portal/ and /static/ on the Funnel port anyway; this keeps a mistaken
    mount (say, ``/``) from exposing the login page and the rest of the app.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "Tailscale-Funnel-Request" in request.headers and not request.path.startswith(
            PUBLIC_PATH_PREFIXES
        ):
            raise Http404
        return self.get_response(request)


class NoCacheMiddleware(MiddlewareMixin):
    """Disable caching in development"""

    def process_response(self, request, response):
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response


class PracticeScopeMiddleware:
    """
    Automatically sets current practice in request based on:
    1. Session cookie ('current_practice_slug')
    2. User's default practice (first practice with ownership)
    3. First available practice

    Sets request.current_practice for use in views and templates.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.current_practice = self.get_practice(request)
        else:
            request.current_practice = None

        response = self.get_response(request)
        return response

    def get_practice(self, request):
        """
        Get current practice for authenticated user.

        Priority:
        1. Session-stored practice slug
        2. User's first practice (where is_owner=True, then any)
        3. None if user has no practices
        """
        from my_practice.models import Practice

        # Try session first
        practice_slug = request.session.get("current_practice_slug")
        if practice_slug:
            practice = Practice.objects.filter(
                slug=practice_slug, users=request.user, is_active=True
            ).first()
            if practice:
                return practice

        # Fall back to user's default practice
        # Prefer owned practices, then any practice
        # Note: memberships__user filter is required to scope the join to current user
        owned_practice = request.user.practices.filter(
            is_active=True,
            memberships__user=request.user,
            memberships__is_owner=True,
        ).first()
        if owned_practice:
            # Store in session for next request
            request.session["current_practice_slug"] = owned_practice.slug
            return owned_practice

        # Any active practice
        any_practice = request.user.practices.filter(is_active=True).first()
        if any_practice:
            request.session["current_practice_slug"] = any_practice.slug
            return any_practice

        return None
