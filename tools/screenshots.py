#!/usr/bin/env python3
"""Capture Woza demo screenshots at phone size for review."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "screenshots"
ZIP_PATH = ROOT / "screenshots.zip"

IPHONE_14_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)

ANIMATION_MS = 850


def close_sheets(page) -> None:
    if page.locator("#sheet.open").count():
        page.locator("#sheetBackdrop").click(force=True)
        page.wait_for_timeout(250)


def js_click(page, element_id: str) -> None:
    page.evaluate("(id) => document.getElementById(id)?.click()", element_id)


def wait_settled(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeout:
        page.wait_for_load_state("load", timeout=8_000)
    page.wait_for_timeout(400)


def snap(page, filename: str, *, full_page: bool = True) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{filename}.png"
    page.screenshot(path=str(path), full_page=full_page)


def run_step(
    results: dict[str, str],
    step_id: str,
    page,
    filename: str,
    action=None,
    *,
    full_page: bool = True,
) -> None:
    try:
        if action:
            action()
        wait_settled(page)
        snap(page, filename, full_page=full_page)
        results[step_id] = "pass"
        print(f"  OK  {step_id} -> {filename}.png")
    except Exception as exc:
        try:
            wait_settled(page)
            snap(page, filename, full_page=full_page)
        except Exception:
            pass
        results[step_id] = f"fail: {exc}"
        print(f"  FAIL {step_id}: {exc} (saved {filename}.png anyway)")


def main() -> int:
    results: dict[str, str] = {}
    print("Starting Woza screenshot run...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
            user_agent=IPHONE_14_UA,
            is_mobile=True,
            has_touch=True,
        )
        request = context.request
        reset_resp = request.post(f"{BASE_URL}/api/reset", timeout=15_000)
        if not reset_resp.ok:
            print(f"Warning: reset demo returned {reset_resp.status}", file=sys.stderr)
        context.clear_cookies()

        page = context.new_page()
        page.set_default_navigation_timeout(20_000)
        page.set_default_timeout(15_000)

        run_step(
            results,
            "01_login",
            page,
            "01_login",
            lambda: page.goto(BASE_URL, wait_until="domcontentloaded"),
        )

        def login_demo() -> None:
            close_sheets(page)
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_selector("#loginView", timeout=10_000)
            page.locator("#demoBtn").click(force=True)
            page.wait_for_selector("#appView:not(.hidden)", timeout=15_000)
            page.wait_for_selector("#memPoints", timeout=15_000)

        run_step(results, "02_home", page, "02_home", login_demo, full_page=True)

        def open_payments() -> None:
            close_sheets(page)
            page.click('nav#tabNav button[data-tab="payments"]')
            page.wait_for_selector("#screenPayments:not(.hidden)", timeout=10_000)
            page.wait_for_selector("#screenPayments button:has-text('Pay')", timeout=10_000)

        run_step(results, "03_payments", page, "03_payments", open_payments)

        def open_pay_sheet() -> None:
            open_payments()
            page.locator("#screenPayments button:has-text('Pay')").first.click()
            page.wait_for_selector("#sheet.open", timeout=10_000)
            page.wait_for_selector("#confirmPay", timeout=10_000)

        run_step(results, "04_pay_sheet", page, "04_pay_sheet", open_pay_sheet, full_page=False)

        def pay_success() -> None:
            open_pay_sheet()
            js_click(page, "confirmPay")
            page.wait_for_selector("text=Paid", timeout=15_000)

        run_step(results, "05_pay_success", page, "05_pay_success", pay_success, full_page=False)

        def home_after_pay() -> None:
            close_sheets(page)
            if page.locator("#donePay").count():
                js_click(page, "donePay")
                page.wait_for_timeout(200)
            page.click('nav#tabNav button[data-tab="home"]')
            page.wait_for_selector("#screenHome:not(.hidden)", timeout=10_000)
            page.wait_for_timeout(ANIMATION_MS)

        run_step(results, "06_home_after_pay", page, "06_home_after_pay", home_after_pay, full_page=True)

        def open_rewards() -> None:
            close_sheets(page)
            page.click('nav#tabNav button[data-tab="rewards"]')
            page.wait_for_selector("#screenRewards:not(.hidden)", timeout=10_000)

        run_step(results, "07_rewards", page, "07_rewards", open_rewards)

        def open_redeem_sheet() -> None:
            open_rewards()
            page.locator('#rewardsPanel button[data-opt="rent"]').click()
            page.wait_for_selector("#sheet.open", timeout=10_000)
            page.wait_for_selector("#confirmRedeem", timeout=10_000)

        run_step(results, "08_redeem_sheet", page, "08_redeem_sheet", open_redeem_sheet, full_page=False)

        def redeem_success() -> None:
            open_redeem_sheet()
            js_click(page, "confirmRedeem")
            page.wait_for_selector("text=Redeemed", timeout=15_000)

        run_step(results, "09_redeem_success", page, "09_redeem_success", redeem_success, full_page=False)

        def benefits_tab() -> None:
            open_rewards()
            if page.locator("#doneR").count():
                js_click(page, "doneR")
                page.wait_for_timeout(200)
            page.click('#screenRewards button[data-rtab="benefits"]')
            page.wait_for_selector("text=Your Gold tier", timeout=10_000)

        run_step(results, "10_rewards_benefits_tab", page, "10_rewards_benefits_tab", benefits_tab)

        def progress_tab() -> None:
            open_rewards()
            page.click('#screenRewards button[data-rtab="progress"]')
            page.wait_for_selector("#rewardsPanel .timeline", timeout=10_000)

        run_step(results, "11_rewards_progress_tab", page, "11_rewards_progress_tab", progress_tab)

        def profile_tab() -> None:
            close_sheets(page)
            page.click('nav#tabNav button[data-tab="profile"]')
            page.wait_for_selector("#screenProfile:not(.hidden)", timeout=10_000)
            page.wait_for_selector("text=Verified member since Oct 2023", timeout=10_000)

        run_step(results, "12_profile", page, "12_profile", profile_tab)

        browser.close()

    if OUT_DIR.exists():
        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
            for png in sorted(OUT_DIR.glob("*.png")):
                zf.write(png, arcname=f"screenshots/{png.name}")
        print(f"\nWrote {ZIP_PATH}")

    passed = sum(1 for v in results.values() if v == "pass")
    failed = len(results) - passed
    print(f"\nSummary: {passed} passed, {failed} failed (of {len(results)} steps)")
    for step_id, status in results.items():
        mark = "PASS" if status == "pass" else "FAIL"
        print(f"  [{mark}] {step_id}" + ("" if status == "pass" else f" — {status}"))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
