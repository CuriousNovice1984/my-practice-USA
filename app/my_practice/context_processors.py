"""Template context shared by every page."""

from django.http import HttpRequest
from django.utils import timezone

from .scenes import Scene, greeting, scene_for


def scene(request: HttpRequest) -> dict[str, Scene | str]:
    """The photograph behind the current page, plus the time-of-day greeting."""
    match = getattr(request, "resolver_match", None)
    hour = timezone.localtime().hour
    return {
        "scene": scene_for(match.url_name if match else None, hour),
        "greeting": greeting(hour),
    }
