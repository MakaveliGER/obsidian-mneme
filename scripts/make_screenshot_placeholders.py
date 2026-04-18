"""Generate placeholder PNGs for the README screenshot slots.

Creates three dark-navy + gold images in Mneme brand colours so the
GitHub landing page doesn't show broken-image icons while real
screenshots are being produced. Run once; commit the resulting PNGs;
replace them with actual screenshots when available.

    uv tool run --with pillow python scripts/make_screenshot_placeholders.py
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


NAVY = (26, 26, 46)       # --mneme-dark
GOLD = (201, 168, 76)     # --mneme-gold
PURPLE = (124, 58, 237)   # --mneme-purple
MUTED = (150, 150, 170)


def load_font(size: int) -> ImageFont.ImageFont:
    """Best-effort serif font discovery on the typical Windows paths."""
    for path in [
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/cambria.ttc",
        "C:/Windows/Fonts/segoeui.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_placeholder(out_path: Path, title: str, subtitle: str) -> None:
    width, height = 1200, 600
    img = Image.new("RGB", (width, height), NAVY)
    draw = ImageDraw.Draw(img)

    draw.rectangle([8, 8, width - 8, height - 8], outline=GOLD, width=2)

    label_font = load_font(22)
    draw.text((40, 30), "OBSIDIAN MNEME — PLACEHOLDER", fill=GOLD, font=label_font)

    title_font = load_font(56)
    title_width = draw.textlength(title, font=title_font)
    draw.text(
        ((width - title_width) // 2, height // 2 - 80),
        title,
        fill=GOLD,
        font=title_font,
    )

    sub_font = load_font(26)
    sub_width = draw.textlength(subtitle, font=sub_font)
    draw.text(
        ((width - sub_width) // 2, height // 2 + 10),
        subtitle,
        fill=MUTED,
        font=sub_font,
    )

    hint_font = load_font(18)
    hint = "Screenshot folgt — siehe docs/testing/screenshot-todo.md"
    hint_width = draw.textlength(hint, font=hint_font)
    draw.text(
        ((width - hint_width) // 2, height - 60),
        hint,
        fill=PURPLE,
        font=hint_font,
    )

    img.save(out_path, "PNG", optimize=True)
    print(f"  created {out_path} ({out_path.stat().st_size} bytes)")


def main() -> None:
    out_dir = Path("design/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        (out_dir / "plugin-search.png", "Plugin-Suche", "Semantische Suche im Obsidian-Plugin"),
        (out_dir / "claudian-toolcall.png", "Claude Desktop + Mneme", "search_notes-Tool-Call im Chat"),
        (out_dir / "plugin-health.png", "Vault Health", "Orphans · Weak Links · Stale · Duplicates"),
    ]
    for path, title, subtitle in specs:
        make_placeholder(path, title, subtitle)
    print("done")


if __name__ == "__main__":
    main()
