#!/usr/bin/env python3
"""Turn a real photo or video clip into the web-ready files a scene uses.

The interface backdrops are real photography (and, where available, real
footage) served from app/static/scenes/ — never hotlinked, because the app
runs behind a tailnet with no outbound calls. This script produces the exact
variants the templates expect, so swapping a scene's photo or adding footage is
one command plus a line in app/my_practice/scenes.py.

    scripts/scene_media.py image dawn ~/Pictures/lake.jpg
    scripts/scene_media.py video dawn ~/Videos/lake-at-dawn.mp4 --start 10 --loop fade

image  -> <key>-2560.webp, <key>-1280.webp (hero sizes, srcset) and
          <key>-ambient.webp (48px wide; the browser blurs it into the page
          backdrop, so the whole page carries the scene's light for ~1 KB).
video  -> <key>.mp4 (H.264, no audio, faststart, <=1920px wide; --start and
          --seconds pick the segment, --loop fade|bounce makes it loop with no
          visible jump) and <key>-poster.webp (its first frame).

Needs Pillow and, for video, ffmpeg on PATH. Record the photographer, source
URL and license in scenes.py and app/static/scenes/CREDITS.md whenever
you add something.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "scenes"
HERO_WIDTHS = (2560, 1280)


def _save_webp(img: Image.Image, path: Path, quality: int) -> None:
    img.save(path, "WEBP", quality=quality, method=6)
    print(f"  {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB  {img.width}x{img.height}")


def process_image(key: str, src: Path, quality: int) -> None:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    for width in HERO_WIDTHS:
        w = min(width, img.width)
        resized = img.resize((w, round(img.height * w / img.width)), Image.LANCZOS)
        _save_webp(resized, OUT / f"{key}-{width}.webp", quality)
    ambient = img.resize((48, max(1, round(img.height * 48 / img.width))), Image.LANCZOS)
    _save_webp(ambient.filter(ImageFilter.GaussianBlur(1.2)), OUT / f"{key}-ambient.webp", 60)
    avg = img.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    print(f"  average colour #{avg[0]:02x}{avg[1]:02x}{avg[2]:02x}")


def _loop_filter(seconds: float, loop: str, fade: float) -> str:
    """Video filter that makes the kept segment loop without a visible jump.

    fade:   the last `fade` seconds dissolve into the first ones, so the final
            frame is the opening frame again (good for clips with steady motion,
            e.g. a drone push or a cloud time-lapse).
    bounce: the segment plays forward then backward (good for very slow drift,
            where reversed motion is imperceptible: stars, a gentle pan).
    """
    scale = "scale='min(1920,iw)':-2"
    if loop == "bounce":
        return f"[0:v]{scale},split[f][r];[r]reverse[b];[f][b]concat=n=2:v=1:a=0[v]"
    if loop == "fade":
        body = seconds - fade
        return (
            f"[0:v]{scale},split[x][y];"
            f"[x]trim=start={fade}:end={seconds},setpts=PTS-STARTPTS[a];"
            f"[y]trim=start=0:end={fade},setpts=PTS-STARTPTS[b];"
            f"[a][b]xfade=transition=fade:duration={fade}:offset={body - fade}[v]"
        )
    return f"[0:v]{scale}[v]"


def process_video(
    key: str, src: Path, start: float, seconds: float, crf: int, loop: str, fade: float
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found on PATH")
    mp4 = OUT / f"{key}.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(seconds),
            "-i",
            str(src),
            "-filter_complex",
            _loop_filter(seconds, loop, fade),
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    print(f"  {mp4.relative_to(ROOT)}  {mp4.stat().st_size // 1024} KB")
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "poster.png"
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), "-frames:v", "1", str(frame)],
            check=True,
        )
        _save_webp(Image.open(frame).convert("RGB"), OUT / f"{key}-poster.webp", 76)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("kind", choices=("image", "video"))
    parser.add_argument("key", help="scene key, e.g. dawn, clients, focus")
    parser.add_argument("src", type=Path)
    parser.add_argument("--quality", type=int, default=74, help="WebP quality (image)")
    parser.add_argument(
        "--start", type=float, default=0, help="where the kept segment starts (video)"
    )
    parser.add_argument("--seconds", type=float, default=20, help="segment length to keep (video)")
    parser.add_argument(
        "--loop",
        choices=("fade", "bounce", "none"),
        default="fade",
        help="how the clip loops seamlessly (video)",
    )
    parser.add_argument("--fade", type=float, default=1.5, help="crossfade length for --loop fade")
    parser.add_argument(
        "--crf", type=int, default=26, help="H.264 quality, lower is better (video)"
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{args.kind} → {args.key}")
    if args.kind == "image":
        process_image(args.key, args.src, args.quality)
    else:
        process_video(args.key, args.src, args.start, args.seconds, args.crf, args.loop, args.fade)


if __name__ == "__main__":
    main()
