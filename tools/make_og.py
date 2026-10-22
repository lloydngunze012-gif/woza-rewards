#!/usr/bin/env python3
"""Render static/og.html to static/og.jpg (1200x630 JPEG) for link previews.

Local only: run this on a developer machine. The JPEG is committed and served
as a static file. Render must not install Playwright or generate the image.
"""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

from PIL import ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OG_HTML = ROOT / "static" / "og.html"
OUT_PATH = ROOT / "static" / "og.jpg"
MAX_BYTES = 300 * 1024
SORA_PATH = ROOT / "tools" / ".sora-bold.ttf"
SORA_URL = "https://github.com/google/fonts/raw/main/ofl/sora/Sora%5Bwght%5D.ttf"
WORDMARK = "Woza"


def ensure_sora_bold() -> Path:
    if SORA_PATH.is_file() and SORA_PATH.stat().st_size > 10_000:
        return SORA_PATH
    req = Request(SORA_URL, headers={"User-Agent": "woza-og"})
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
    if len(data) < 10_000:
        raise SystemExit(f"Sora download too small ({len(data)} bytes)")
    SORA_PATH.write_bytes(data)
    return SORA_PATH


def sora_700(size_px: float) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(ensure_sora_bold()), size=round(size_px))
    font.set_variation_by_axes([700])
    return font


def cap_center_from_baseline(font: ImageFont.FreeTypeFont, text: str) -> float:
    """Midpoint of ink top and the baseline, ignoring descender space."""
    _left, top, _right, _bottom = font.getbbox(text, anchor="ls")
    return (top + 0) / 2


def cap_center_from_css_top(
    font: ImageFont.FreeTypeFont, text: str, line_height_px: float
) -> float:
    ascent, descent = font.getmetrics()
    half_leading = (line_height_px - (ascent + descent)) / 2
    baseline_from_top = half_leading + ascent
    return baseline_from_top + cap_center_from_baseline(font, text)


def align_wordmark_to_circle(page) -> None:
    info = page.evaluate(
        """() => {
          const word = document.querySelector(".wordmark");
          const mark = document.querySelector(".mark");
          if (!word || !mark) return null;
          const wcs = getComputedStyle(word);
          const wr = word.getBoundingClientRect();
          const mr = mark.getBoundingClientRect();
          return {
            fontSize: parseFloat(wcs.fontSize),
            lineHeight: parseFloat(wcs.lineHeight),
            wordY: wr.y,
            markY: mr.y,
            markH: mr.height,
          };
        }"""
    )
    if not info:
        raise SystemExit("OG lockup (.mark / .wordmark) not found")

    font = sora_700(info["fontSize"])
    current_cap_cy = info["wordY"] + cap_center_from_css_top(
        font, WORDMARK, info["lineHeight"]
    )
    circle_cy = info["markY"] + info["markH"] / 2
    delta = circle_cy - current_cap_cy
    print(
        f"lockup align: circle_cy={circle_cy:.1f} cap_cy={current_cap_cy:.1f} "
        f"translateY={delta:.1f}px"
    )
    page.locator(".wordmark").evaluate(
        "(el, d) => { el.style.transform = `translateY(${d}px)`; }",
        delta,
    )


def main() -> int:
    if not OG_HTML.is_file():
        raise SystemExit(f"Missing {OG_HTML}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1200, "height": 630},
            device_scale_factor=1,
        )
        page.goto(OG_HTML.resolve().as_uri(), wait_until="networkidle")
        page.wait_for_selector(".membership-card.tier-gold", timeout=15_000)
        page.evaluate("() => document.fonts.ready")
        page.wait_for_timeout(400)
        align_wordmark_to_circle(page)
        page.screenshot(path=str(OUT_PATH), type="jpeg", quality=82, full_page=False)
        browser.close()

    size = OUT_PATH.stat().st_size
    print(f"Wrote {OUT_PATH}")
    print(f"size: {size} bytes ({size / 1024:.1f} KB)")
    if size >= MAX_BYTES:
        raise SystemExit(f"og.jpg is {size} bytes; must be under {MAX_BYTES} (300 KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
