"""Template tags for the photographic shell: scenes (my_practice/scenes.py) and page titles."""

import re

from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

from ..scenes import SCENES, Scene

register = template.Library()

# Pictographs, dingbats and symbol emoji plus their joiners and variation
# selectors. Arrows (←, →) and ⌘ are deliberately not in these ranges.
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍⃣]+[ \t]*")


@register.simple_tag
def get_scene(key: str) -> Scene:
    """{% get_scene "notfound" as scene %} — for pages that pick their own scene."""
    return SCENES[key]


@register.simple_tag
def scene_image(scene: Scene, css_class: str = "scene__img", loading: str = "eager") -> SafeString:
    """The scene photograph as a responsive <img>, cropped around its focal point."""
    small = static(f"{scene.base}-1280.webp")
    large = static(f"{scene.base}-2560.webp")
    return format_html(
        '<img class="{}" src="{}" srcset="{} 1280w, {} 2560w" sizes="100vw" alt="{}" '
        'style="object-position: {}" loading="{}" decoding="async"{}>',
        css_class,
        small,
        small,
        large,
        scene.alt,
        scene.focus,
        loading,
        mark_safe(' fetchpriority="high"') if loading == "eager" else "",
    )


@register.simple_tag
def scene_video(scene: Scene) -> SafeString | str:
    """Footage for scenes that have it. The source is attached by base.html's script
    only when ambient motion is on, so reduced-motion visitors never download it."""
    if not scene.video:
        return ""
    return format_html(
        '<video class="scene__video" data-scene-video data-src="{}" poster="{}" muted loop '
        'playsinline preload="none" aria-hidden="true" style="object-position: {}"></video>',
        static(f"{scene.base}.mp4"),
        static(f"{scene.base}-poster.webp"),
        scene.focus,
    )


@register.simple_tag
def scene_ambient(scene: Scene) -> str:
    """URL of the tiny version of the photograph the page backdrop is washed with."""
    return static(f"{scene.base}-ambient.webp")


@register.filter(is_safe=True)
def strip_emoji(value: str) -> str:
    """Drop emoji from a rendered block, e.g. page titles set in the hero's serif."""
    return _EMOJI.sub("", str(value)).strip()
