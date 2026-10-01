#!/usr/bin/env python3
"""Turn a real photo or video clip into the web-ready files a scene uses.

The interface backdrops are real photography (and, where available, real
footage) served from app/static/scenes/ — never hotlinked, because the app
runs behind a tailnet with no outbound calls. This script produces the exact
variants the templates expect, so swapping a scene's photo or adding footage is
one command plus a line in app/my_practice/scenes.py.

    scripts/scene_media.py image dawn ~/Pictures/lake.jpg
    scripts/scene_media.py video dawn ~/Videos/lake-at-dawn.mp4

image  -> <key>-2560.webp, <key>-1280.webp (hero sizes, srcset) and
          <key>-ambient.webp (48px wide; the browser blurs it into the page
          backdrop, so the whole page carries the scene's light for ~1 KB).
video  -> <key>.mp4 (H.264, no audio, faststart, <=1920px wide, trimmed to
          --seconds) and <key>-poster.webp (first frame, shown until the video
          plays and to anyone with reduced motion).

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


def process_video(key: str, src: Path, seconds: int, crf: int) -> None:
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
            "-i",
            str(src),
            "-t",
            str(seconds),
            "-vf",
            "scale='min(1920,iw)':-2,fps=30",
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
    parser.add_argument("--seconds", type=int, default=20, help="clip length to keep (video)")
    parser.add_argument(
        "--crf", type=int, default=26, help="H.264 quality, lower is better (video)"
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{args.kind} → {args.key}")
    if args.kind == "image":
        process_image(args.key, args.src, args.quality)
    else:
        process_video(args.key, args.src, args.seconds, args.crf)


if __name__ == "__main__":
    main()
