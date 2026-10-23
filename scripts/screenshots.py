#!/usr/bin/env python3
"""Capture every Woza screen for visual review.

This file is the single list of screens. Add a new capture here whenever a
new screen or state is added.

Usage:
  python scripts/screenshots.py
  python scripts/screenshots.py --url https://woza-rewards.onrender.com
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
LATEST_DIR = ROOT / "docs" / "screens" / "latest"
HISTORY_DIR = ROOT / "docs" / "screens" / "history"
DEMO_NAME = "Thandi"
VIEWPORT = {"width": 390, "height": 844}
DEVICE_SCALE_FACTOR = 2

# Ordered list of captures. Each name becomes <name>.png.
# Add a new name + capture_* function whenever a screen or state is added.
SCREENS = [
    "login",
    "home",
    "home_card_back",
    "payments",
    "pay_rent",
    "grace",
    "rewards",
    "rewards_benefits",
    "record",
    "share_consent",
    "lender_view",
    "what_if",
    "settings",
]


def git_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or "nogit"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "nogit"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(base_url: str, timeout: float = 40.0) -> None:
    url = base_url.rstrip("/") + "/api/health"
    deadline = time.time() + timeout
    last_err = "no response"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return
                last_err = f"HTTP {resp.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"app did not become ready at {url}: {last_err}")


def start_app(port: int) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    kwargs: dict = {
        "cwd": str(ROOT),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        wait_health(f"http://127.0.0.1:{port}")
    except Exception:
        stop_app(proc)
        raise
    return proc


def stop_app(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def wait_settled(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeout:
        page.wait_for_load_state("load", timeout=8_000)
    try:
        page.evaluate("() => document.fonts ? document.fonts.ready : null")
    except Exception:
        pass
    page.wait_for_timeout(350)


def close_sheets(page: Page) -> None:
    page.evaluate(
        """() => {
          document.getElementById("sheet")?.classList.remove("open");
          document.getElementById("sheetBackdrop")?.classList.remove("open");
        }"""
    )
    page.wait_for_timeout(120)


def show_tab(page: Page, tab: str) -> None:
    close_sheets(page)
    page.click(f'nav#tabNav button[data-tab="{tab}"]')
    screen_id = {
        "home": "screenHome",
        "payments": "screenPayments",
        "rewards": "screenRewards",
        "record": "screenRecord",
    }[tab]
    page.wait_for_selector(f"#{screen_id}:not(.hidden)", timeout=10_000)


def sign_in(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_selector("#tryThandiBtn", timeout=15_000)
    page.locator("#tryThandiBtn").click(force=True)
    page.wait_for_selector("#appView:not(.hidden)", timeout=20_000)
    page.wait_for_selector("#screenHome .mem-points", timeout=15_000)


def reset_demo(page: Page, base_url: str) -> None:
    resp = page.request.post(
        f"{base_url.rstrip('/')}/api/reset",
        data=json.dumps({"name": DEMO_NAME}),
        headers={"Content-Type": "application/json"},
        timeout=15_000,
    )
    if not resp.ok:
        raise RuntimeError(f"reset demo returned {resp.status}")
    page.goto(base_url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("#appView:not(.hidden)", timeout=8_000)
    except PlaywrightTimeout:
        sign_in(page, base_url)
    page.wait_for_selector("#screenHome .mem-points", timeout=15_000)
    wait_settled(page)


def content_height(page: Page) -> int:
    return int(
        page.evaluate(
            """() => {
              const screen = document.querySelector('#appView:not(.hidden) .screen:not(.hidden)');
              const login = document.querySelector('#loginView:not(.hidden)');
              const el = screen || login || document.body;
              return Math.max(el.scrollHeight || 0, el.offsetHeight || 0, 844);
            }"""
        )
    )


def snap(page: Page, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size(VIEWPORT)
    sheet = page.locator("#sheet.open")
    if sheet.count() and sheet.is_visible():
        page.screenshot(path=str(dest), full_page=False)
        return
    height = max(VIEWPORT["height"], content_height(page) + 8)
    page.set_viewport_size({"width": VIEWPORT["width"], "height": height})
    page.wait_for_timeout(80)
    page.screenshot(path=str(dest), full_page=True)
    page.set_viewport_size(VIEWPORT)


def capture_login(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_selector("#loginView", timeout=15_000)
    page.wait_for_selector("#tryThandiBtn", timeout=10_000)
    page.wait_for_selector("#displayName", timeout=10_000)
    page.wait_for_selector("#loginBtn", timeout=10_000)


def capture_home(page: Page) -> None:
    show_tab(page, "home")
    page.wait_for_selector("#screenHome .mem-tier", timeout=10_000)
    page.wait_for_selector("#streakWheel", timeout=10_000)
    page.wait_for_selector("#thisMonth", timeout=10_000)
    page.wait_for_selector("#homePayWoza, #screenHome .home-status", timeout=15_000)


def capture_home_card_back(page: Page) -> None:
    show_tab(page, "home")
    page.wait_for_selector("#screenHome [data-card-flip]", timeout=10_000)
    page.evaluate("document.querySelector('#screenHome [data-card-flip]')?.click()")
    page.wait_for_selector("#screenHome .card-flip.is-flipped", timeout=8_000)
    page.wait_for_timeout(650)


def capture_payments(page: Page) -> None:
    show_tab(page, "payments")
    page.wait_for_selector("#screenPayments .bill-row", timeout=10_000)


def capture_pay_rent(page: Page) -> None:
    show_tab(page, "payments")
    page.locator("#screenPayments button:has-text('Pay')").first.click()
    page.wait_for_selector("#sheet.open", timeout=10_000)
    page.wait_for_selector("#confirmPay", timeout=10_000)


def capture_grace(page: Page) -> None:
    show_tab(page, "home")
    grace_btn = page.locator("#homeNudge")
    if grace_btn.count() and grace_btn.is_visible():
        grace_btn.click()
        page.wait_for_selector("#sheet.open", timeout=8_000)
        page.wait_for_selector("#confirmGrace", timeout=8_000)
        return
    show_tab(page, "record")
    page.wait_for_selector("text=Grace months", timeout=10_000)
    page.wait_for_selector("#screenRecord .progress-item", timeout=10_000)


def capture_rewards(page: Page) -> None:
    show_tab(page, "rewards")
    page.click('#screenRewards button[data-rtab="redeem"]')
    page.wait_for_selector("#rewardsPanel [data-opt]", timeout=10_000)


def capture_rewards_benefits(page: Page) -> None:
    show_tab(page, "rewards")
    page.click('#screenRewards button[data-rtab="benefits"]')
    page.wait_for_selector("#rewardsPanel >> text=Your Gold tier", timeout=10_000)


def capture_record(page: Page) -> None:
    show_tab(page, "record")
    page.wait_for_selector("#screenRecord:not(.hidden)", timeout=10_000)
    page.wait_for_selector("#screenRecord .progress-item", timeout=10_000)
    page.wait_for_selector("#shareRecordBtn", timeout=10_000)
    page.wait_for_selector("#screenRecord >> text=shared with the credit bureau", timeout=10_000)


def capture_share_consent(page: Page) -> None:
    show_tab(page, "record")
    page.wait_for_selector("#shareRecordBtn", timeout=10_000)
    page.click("#shareRecordBtn")
    page.wait_for_selector("#sheet.open", timeout=10_000)
    page.wait_for_selector("#confirmShare", timeout=10_000)


def open_lender_view(page: Page) -> None:
    show_tab(page, "record")
    if page.locator("#screenRecord >> text=Lender view").count():
        page.wait_for_selector("#simulateLateBtn, #undoLateBtn", timeout=10_000)
        return
    page.wait_for_selector("#shareRecordBtn", timeout=10_000)
    page.click("#shareRecordBtn")
    page.wait_for_selector("#confirmShare", timeout=10_000)
    page.click("#confirmShare")
    page.wait_for_selector("#screenRecord >> text=Lender view", timeout=15_000)
    page.wait_for_selector("#simulateLateBtn, #undoLateBtn", timeout=15_000)


def capture_lender_view(page: Page) -> None:
    open_lender_view(page)
    page.wait_for_selector("#screenRecord >> text=Before Woza", timeout=10_000)
    page.wait_for_selector("#screenRecord .forecast-bill", timeout=10_000)
    page.wait_for_selector("#screenRecord .forecast-disclosure", timeout=10_000)


def capture_what_if(page: Page) -> None:
    open_lender_view(page)
    undo = page.locator("#undoLateBtn")
    if undo.count() and undo.is_visible():
        page.wait_for_selector("#screenRecord .forecast-bill", timeout=10_000)
        return
    page.wait_for_selector("#simulateLateBtn", timeout=10_000)
    with page.expect_response(lambda r: "/api/demo/simulate_late" in r.url and r.request.method == "POST"):
        page.click("#simulateLateBtn")
    page.wait_for_selector("#undoLateBtn", timeout=15_000)
    page.wait_for_timeout(800)


def capture_settings(page: Page) -> None:
    show_tab(page, "home")
    page.click("#homeGear")
    page.wait_for_selector("#sheet.open", timeout=10_000)
    page.wait_for_selector("#resetBtn", timeout=10_000)


CAPTURE_FNS = {
    "login": lambda page, base_url: capture_login(page, base_url),
    "home": lambda page, base_url: capture_home(page),
    "home_card_back": lambda page, base_url: capture_home_card_back(page),
    "payments": lambda page, base_url: capture_payments(page),
    "pay_rent": lambda page, base_url: capture_pay_rent(page),
    "grace": lambda page, base_url: capture_grace(page),
    "rewards": lambda page, base_url: capture_rewards(page),
    "rewards_benefits": lambda page, base_url: capture_rewards_benefits(page),
    "record": lambda page, base_url: capture_record(page),
    "share_consent": lambda page, base_url: capture_share_consent(page),
    "lender_view": lambda page, base_url: capture_lender_view(page),
    "what_if": lambda page, base_url: capture_what_if(page),
    "settings": lambda page, base_url: capture_settings(page),
}


def load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_contact_sheet(latest: Path, names: list[str], commit: str, stamp: str) -> Path:
    thumb_w = 220
    label_h = 28
    gap = 16
    header_h = 64
    pad = 24
    cols = 4
    images: list[tuple[str, Image.Image]] = []
    for name in names:
        src = latest / f"{name}.png"
        if not src.is_file():
            continue
        im = Image.open(src).convert("RGB")
        ratio = thumb_w / im.width
        thumb = im.resize((thumb_w, max(1, int(im.height * ratio))), Image.Resampling.LANCZOS)
        images.append((name, thumb))
    if not images:
        raise RuntimeError("no screenshots to put on the contact sheet")

    rows = (len(images) + cols - 1) // cols
    cell_h = max(t.height for _, t in images) + label_h
    width = pad * 2 + cols * thumb_w + (cols - 1) * gap
    height = pad + header_h + rows * cell_h + (rows - 1) * gap + pad
    sheet = Image.new("RGB", (width, height), (246, 244, 251))
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(22)
    small_font = load_font(14)
    label_font = load_font(13)
    draw.text((pad, 16), "Woza Rewards screens", fill=(28, 21, 48), font=title_font)
    draw.text((pad, 42), f"{commit}  ·  {stamp}", fill=(107, 100, 133), font=small_font)

    for i, (name, thumb) in enumerate(images):
        r, c = divmod(i, cols)
        x = pad + c * (thumb_w + gap)
        y = pad + header_h + r * (cell_h + gap)
        sheet.paste(thumb, (x, y))
        draw.text((x, y + thumb.height + 6), name, fill=(28, 21, 48), font=label_font)

    out = latest / "contact-sheet.png"
    sheet.save(out, "PNG")
    return out


def copy_latest_to_history(latest: Path, history: Path) -> None:
    history.mkdir(parents=True, exist_ok=True)
    for png in latest.glob("*.png"):
        dest = history / png.name
        dest.write_bytes(png.read_bytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Woza screens for review")
    parser.add_argument("--url", help="Existing app URL (skip starting a local server)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commit = git_short()
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d_%H%M")
    history = HISTORY_DIR / f"{stamp}_{commit}"
    if history.exists():
        n = 2
        while True:
            alt = HISTORY_DIR / f"{stamp}_{commit}_{n}"
            if not alt.exists():
                history = alt
                break
            n += 1

    proc = None
    base_url = (args.url or "").rstrip("/")
    if not base_url:
        port = free_port()
        print(f"Starting app on http://127.0.0.1:{port}", flush=True)
        proc = start_app(port)
        base_url = f"http://127.0.0.1:{port}"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    for old in LATEST_DIR.glob("*.png"):
        old.unlink()

    failed: list[str] = []
    captured: list[str] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=DEVICE_SCALE_FACTOR,
                is_mobile=True,
                has_touch=True,
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_navigation_timeout(25_000)
            page.set_default_timeout(15_000)

            print("Login + reset demo...", flush=True)
            capture_login(page, base_url)
            wait_settled(page)
            snap(page, LATEST_DIR / "login.png")
            captured.append("login")
            print("  OK  login", flush=True)

            sign_in(page, base_url)
            reset_demo(page, base_url)

            for name in SCREENS:
                if name == "login":
                    continue
                try:
                    close_sheets(page)
                    if name == "home_card_back":
                        show_tab(page, "home")
                    CAPTURE_FNS[name](page, base_url)
                    wait_settled(page)
                    snap(page, LATEST_DIR / f"{name}.png")
                    captured.append(name)
                    print(f"  OK  {name}", flush=True)
                    if name == "home_card_back":
                        page.evaluate(
                            "document.querySelector('#screenHome [data-card-flip]')?.click()"
                        )
                        page.wait_for_timeout(400)
                    if name in ("pay_rent", "settings", "share_consent"):
                        close_sheets(page)
                    if name == "what_if":
                        undo = page.locator("#undoLateBtn")
                        if undo.count() and undo.is_visible():
                            undo.click()
                            page.wait_for_timeout(400)
                except Exception as exc:
                    failed.append(f"{name}: {exc}")
                    try:
                        snap(page, LATEST_DIR / f"{name}.png")
                    except Exception:
                        pass
                    print(f"  FAIL {name}: {exc}", flush=True)

            context.close()
            browser.close()
    finally:
        stop_app(proc)

    copy_latest_to_history(LATEST_DIR, history)
    contact = build_contact_sheet(
        LATEST_DIR,
        SCREENS,
        commit,
        now.strftime("%Y-%m-%d %H:%M"),
    )
    contact_hist = history / "contact-sheet.png"
    contact_hist.write_bytes(contact.read_bytes())

    print(f"\nLatest:         {LATEST_DIR}")
    print(f"History:        {history}")
    print(f"Contact sheet:  {contact}")
    if failed:
        print("\nFailed captures:")
        for item in failed:
            print(f"  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
