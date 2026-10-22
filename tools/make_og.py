#!/usr/bin/env python3
"""Render static/og.html to static/og.png (1200x630) for link previews."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OG_HTML = ROOT / "static" / "og.html"
OUT_PATH = ROOT / "static" / "og.png"


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
        page.screenshot(path=str(OUT_PATH), type="png", full_page=False)
        browser.close()

    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
