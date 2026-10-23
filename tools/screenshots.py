#!/usr/bin/env python3
"""Capture Woza demo screenshots at phone size for review."""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from typing import Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "screenshots"
ZIP_PATH = ROOT / "screenshots.zip"

VIEWPORTS: list[tuple[int, int, str]] = [
    (390, 844, "390"),
    (360, 800, "360"),
]

IPHONE_14_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)

ANIMATION_MS = 850
DEMO_NAME = "Thandi"


def prepare_output_dir() -> None:
    """Drop prior captures and zip so this run is the only artifact set."""
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()


def close_sheets(page: Page) -> None:
    page.evaluate(
        """() => {
          document.getElementById("sheet")?.classList.remove("open");
          document.getElementById("sheetBackdrop")?.classList.remove("open");
        }"""
    )
    page.wait_for_timeout(150)


def js_click(page: Page, element_id: str) -> None:
    page.evaluate("(id) => document.getElementById(id)?.click()", element_id)


def sign_in(page: Page, name: str = DEMO_NAME) -> None:
    page.wait_for_selector("#displayName", timeout=10_000)
    page.locator("#displayName").fill(name)
    page.locator("#loginBtn").click(force=True)
    page.wait_for_selector("#appView:not(.hidden)", timeout=15_000)


def wait_settled(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeout:
        page.wait_for_load_state("load", timeout=8_000)
    page.wait_for_timeout(400)


def assert_no_horizontal_overflow(page: Page) -> None:
    metrics = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        })"""
    )
    if metrics["scrollWidth"] > metrics["innerWidth"]:
        raise RuntimeError(
            f"horizontal overflow: scrollWidth={metrics['scrollWidth']} "
            f"> innerWidth={metrics['innerWidth']}"
        )


def snap(page: Page, out_dir: Path, filename: str, *, full_page: bool = True) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{filename}.png"
    page.screenshot(path=str(path), full_page=full_page)


def run_step(
    results: dict[str, str],
    step_key: str,
    page: Page,
    out_dir: Path,
    filename: str,
    action: Callable[[], None] | None = None,
    *,
    full_page: bool = False,
) -> None:
    try:
        if action:
            action()
        wait_settled(page)
        assert_no_horizontal_overflow(page)
        snap(page, out_dir, filename, full_page=full_page)
        results[step_key] = "pass"
        print(f"  OK  {step_key} -> {out_dir.name}/{filename}.png")
    except Exception as exc:
        try:
            wait_settled(page)
            snap(page, out_dir, filename, full_page=full_page)
        except Exception:
            pass
        results[step_key] = f"fail: {exc}"
        print(f"  FAIL {step_key}: {exc} (saved {out_dir.name}/{filename}.png anyway)")


def run_all_steps(page: Page, out_dir: Path, results: dict[str, str], prefix: str) -> None:
    def key(step_id: str) -> str:
        return f"{prefix}/{step_id}"

    run_step(
        results,
        key("01_login"),
        page,
        out_dir,
        "01_login",
        lambda: (
            page.goto(BASE_URL, wait_until="domcontentloaded"),
            page.wait_for_selector(".login-mark", timeout=10_000),
            page.wait_for_selector("#displayName", timeout=10_000),
            page.wait_for_selector("label[for='displayName']", timeout=10_000),
            page.wait_for_selector("text=Everything you see is a private demo. No real money moves.", timeout=10_000),
            page.wait_for_selector("#continueAsThandi", timeout=10_000),
        )[0],
    )

    def login_demo() -> None:
        close_sheets(page)
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#loginView", timeout=10_000)
        sign_in(page)
        page.wait_for_selector(".mem-points", timeout=15_000)
        page.wait_for_selector("text=12 months to Black", timeout=10_000)
        page.wait_for_selector("#screenHome .home-greeting", timeout=10_000)
        page.wait_for_selector("#screenHome .home-slogan", timeout=10_000)
        page.wait_for_selector("#screenHome >> text=Pay today. Earn tomorrow.", timeout=10_000)
        page.wait_for_selector("#screenHome .mem-tier:has-text('Gold')", timeout=10_000)
        page.wait_for_selector("text=You: 36 months", timeout=10_000)
        page.wait_for_selector("text=Add a bill", timeout=10_000)
        page.wait_for_timeout(2_000)

    run_step(results, key("02_home"), page, out_dir, "02_home", login_demo, full_page=True)

    def open_payments() -> None:
        close_sheets(page)
        page.click('nav#tabNav button[data-tab="payments"]')
        page.wait_for_selector("#screenPayments:not(.hidden)", timeout=10_000)
        page.wait_for_selector("#screenPayments button:has-text('Pay')", timeout=10_000)
        page.wait_for_selector("#screenPayments >> text=You pay R5 875", timeout=10_000)
        page.wait_for_selector("#screenPayments >> text=R6 000 in bills", timeout=10_000)
        page.wait_for_selector("#screenPayments >> text=Earns 6 000 pts", timeout=10_000)
        page.wait_for_selector("#screenPayments >> text=Add a bill", timeout=10_000)

    run_step(results, key("03_payments"), page, out_dir, "03_payments", open_payments, full_page=True)

    def open_pay_sheet() -> None:
        open_payments()
        page.locator("#screenPayments button:has-text('Pay')").first.click()
        page.wait_for_selector("#sheet.open", timeout=10_000)
        page.wait_for_selector("#confirmPay", timeout=10_000)
        page.wait_for_selector("#sheet >> text=You pay R4 375", timeout=10_000)
        page.wait_for_selector("#sheet >> text=worth up to R67.50 off rent", timeout=10_000)

    run_step(results, key("04_pay_sheet"), page, out_dir, "04_pay_sheet", open_pay_sheet, full_page=False)

    def pay_success() -> None:
        open_pay_sheet()
        with page.expect_response(lambda r: "/api/pay" in r.url and r.request.method == "POST"):
            js_click(page, "confirmPay")
        page.wait_for_function(
            "() => document.querySelector('#sheetBody h3')?.textContent === 'Rent paid'",
            timeout=15_000,
        )
        page.wait_for_timeout(400)
        js_click(page, "donePay")
        page.wait_for_function(
            "() => !document.getElementById('sheet')?.classList.contains('open')",
            timeout=10_000,
        )

    run_step(results, key("05_pay_success"), page, out_dir, "05_pay_success", pay_success, full_page=False)

    def home_after_pay() -> None:
        close_sheets(page)
        if page.locator("#donePay").count():
            js_click(page, "donePay")
            page.wait_for_timeout(200)
        page.click('nav#tabNav button[data-tab="home"]')
        page.wait_for_selector("#screenHome:not(.hidden)", timeout=10_000)
        page.wait_for_timeout(ANIMATION_MS)

    run_step(
        results, key("06_home_after_pay"), page, out_dir, "06_home_after_pay", home_after_pay, full_page=False
    )

    def restore_start() -> None:
        close_sheets(page)
        reset_resp = page.request.post(
            f"{BASE_URL}/api/reset",
            data='{"name": "Thandi"}',
            headers={"Content-Type": "application/json"},
            timeout=15_000,
        )
        if not reset_resp.ok:
            raise RuntimeError(f"reset demo returned {reset_resp.status}")
        page.goto(BASE_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#appView:not(.hidden)", timeout=8_000)
        except PlaywrightTimeout:
            sign_in(page)

    def open_rewards() -> None:
        close_sheets(page)
        page.click('nav#tabNav button[data-tab="rewards"]')
        page.wait_for_selector("#screenRewards:not(.hidden)", timeout=10_000)

    def open_rewards_redeem() -> None:
        restore_start()
        open_rewards()
        page.wait_for_selector("#screenRewards [data-membership-card]", timeout=10_000)
        page.wait_for_selector("#screenRewards .mem-points", timeout=10_000)
        page.wait_for_selector("#screenRewards >> text=12 000", timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="rent"]', timeout=10_000)
        page.wait_for_selector("text=Towards next rent", timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="electricity"]', timeout=10_000)
        page.wait_for_selector("text=Prepaid electricity", timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="data"]', timeout=10_000)
        page.wait_for_selector("text=Data and airtime", timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="fuel"]', timeout=10_000)
        page.wait_for_selector("text=Fuel", timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="groceries"]', timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="ebucks"]', timeout=10_000)
        page.wait_for_selector('#rewardsPanel button[data-opt="cash"]', timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R180 off rent", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R180 of electricity, about 55 units", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R120 of data, about 2 GB", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R120 of fuel, about 5 litres", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R120 at partner stores", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R120 in eBucks", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=R60 to your account", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=1.5c per point", timeout=10_000)
        if page.locator('#rewardsPanel button[data-opt="flights"]').count():
            raise RuntimeError("Flights should be removed from redeem")

    run_step(results, key("07_rewards"), page, out_dir, "07_rewards", open_rewards_redeem, full_page=True)

    def open_redeem_sheet() -> None:
        open_rewards_redeem()
        page.locator('#rewardsPanel button[data-opt="rent"]').click()
        page.wait_for_selector("#sheet.open", timeout=10_000)
        page.wait_for_selector("#confirmRedeem", timeout=10_000)
        page.wait_for_selector("#sheet >> text=All", timeout=10_000)
        page.wait_for_selector("#sheet >> text=Half", timeout=10_000)
        page.wait_for_selector("#sheet >> text=R180 off rent", timeout=10_000)

    run_step(results, key("08_redeem_sheet"), page, out_dir, "08_redeem_sheet", open_redeem_sheet, full_page=False)

    def redeem_success() -> None:
        open_redeem_sheet()
        js_click(page, "confirmRedeem")
        page.wait_for_selector("text=Redeemed", timeout=15_000)
        page.wait_for_selector("text=added to Woza cash", timeout=10_000)
        js_click(page, "doneR")
        page.wait_for_function(
            "() => !document.getElementById('sheet')?.classList.contains('open')",
            timeout=10_000,
        )

    run_step(results, key("09_redeem_success"), page, out_dir, "09_redeem_success", redeem_success, full_page=False)

    def benefits_tab() -> None:
        open_rewards()
        if page.locator("#doneR").count():
            js_click(page, "doneR")
            page.wait_for_timeout(200)
        page.click('#screenRewards button[data-rtab="benefits"]')
        page.wait_for_selector("text=Your Gold tier", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=shared with the credit bureau", timeout=10_000)
        page.wait_for_selector("#rewardsPanel >> text=Priority access to partner offers", timeout=10_000)

    run_step(results, key("10_rewards_benefits_tab"), page, out_dir, "10_rewards_benefits_tab", benefits_tab)

    def progress_tab() -> None:
        open_rewards()
        page.click('#screenRewards button[data-rtab="progress"]')
        page.wait_for_selector("text=Last 12 months", timeout=10_000)
        page.wait_for_selector("#rewardsPanel .cal-grid", timeout=10_000)
        page.wait_for_selector("text=36 months on time", timeout=10_000)

    run_step(results, key("11_rewards_progress_tab"), page, out_dir, "11_rewards_progress_tab", progress_tab)

    def forecast_tab() -> None:
        close_sheets(page)
        page.click('nav#tabNav button[data-tab="forecast"]')
        page.wait_for_selector("#screenForecast:not(.hidden)", timeout=10_000)
        page.wait_for_selector("#screenForecast >> text=on time (predicted)", timeout=10_000)
        page.wait_for_selector("#simulateLateBtn", timeout=10_000)
        page.wait_for_selector("#screenForecast .forecast-disclosure", timeout=10_000)

    run_step(results, key("12_forecast"), page, out_dir, "12_forecast", forecast_tab)

    def card_preview() -> None:
        close_sheets(page)
        page.goto(f"{BASE_URL}/card-preview", wait_until="domcontentloaded")
        page.wait_for_selector(".card-preview-stack [data-membership-card]", timeout=10_000)
        page.wait_for_selector(".membership-card.tier-gold", timeout=10_000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

    run_step(results, key("13_card_preview"), page, out_dir, "13_card_preview", card_preview, full_page=False)

    def card_back() -> None:
        close_sheets(page)
        page.goto(BASE_URL, wait_until="domcontentloaded")
        # boot() may restore the session; do not wait on a hidden login field.
        try:
            page.wait_for_selector("#appView:not(.hidden)", timeout=8_000)
        except PlaywrightTimeout:
            sign_in(page)
        page.wait_for_selector("#screenHome [data-card-flip]", timeout=10_000)
        page.evaluate("document.querySelector('#screenHome [data-card-flip]')?.click()")
        page.wait_for_timeout(700)
        page.wait_for_selector("#screenHome .card-flip.is-flipped", timeout=5_000)

    run_step(results, key("15_card_back"), page, out_dir, "15_card_back", card_back, full_page=False)


def phone_context_kwargs() -> dict:
    return {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "user_agent": IPHONE_14_UA,
        "is_mobile": True,
        "has_touch": True,
    }


def pay_rent(page: Page) -> None:
    page.click('nav#tabNav button[data-tab="payments"]')
    page.wait_for_selector("#screenPayments:not(.hidden)", timeout=10_000)
    page.locator("#screenPayments button:has-text('Pay')").first.click()
    page.wait_for_selector("#sheet.open", timeout=10_000)
    page.wait_for_selector("#confirmPay", timeout=10_000)
    with page.expect_response(lambda r: "/api/pay" in r.url and r.request.method == "POST"):
        js_click(page, "confirmPay")
    page.wait_for_function(
        "() => document.querySelector('#sheetBody h3')?.textContent === 'Rent paid'",
        timeout=15_000,
    )


def run_isolation_step(browser, results: dict[str, str]) -> None:
    step_key = "isolation/two_contexts"
    out_dir = OUT_DIR / "isolation"
    ctx1 = ctx2 = None
    try:
        ctx1 = browser.new_context(**phone_context_kwargs())
        ctx2 = browser.new_context(**phone_context_kwargs())
        page1 = ctx1.new_page()
        page2 = ctx2.new_page()
        for pg in (page1, page2):
            pg.set_default_navigation_timeout(20_000)
            pg.set_default_timeout(15_000)

        page1.goto(BASE_URL, wait_until="domcontentloaded")
        sign_in(page1, "Thandi")
        page1.wait_for_selector("#screenHome .mem-tier:has-text('Gold')", timeout=10_000)

        page2.goto(BASE_URL, wait_until="domcontentloaded")
        sign_in(page2, "Thandi")
        page2.wait_for_selector("#screenHome .mem-tier:has-text('Gold')", timeout=10_000)

        pay_rent(page1)

        page2.click('nav#tabNav button[data-tab="payments"]')
        page2.wait_for_selector("#screenPayments:not(.hidden)", timeout=10_000)
        page2.wait_for_selector(
            "#screenPayments .bill-row:has-text('Rent') button:has-text('Pay')",
            timeout=10_000,
        )
        page2.wait_for_selector(
            "#screenPayments .bill-row:has-text('Rent') >> text=Due 1 Nov",
            timeout=10_000,
        )
        wait_settled(page2)
        snap(page2, out_dir, "16_second_browser_rent_due", full_page=True)
        results[step_key] = "pass"
        print(f"  OK  {step_key} -> isolation/16_second_browser_rent_due.png")
    except Exception as exc:
        try:
            if ctx2 is not None:
                pages = ctx2.pages
                if pages:
                    snap(pages[0], out_dir, "16_second_browser_rent_due", full_page=True)
        except Exception:
            pass
        results[step_key] = f"fail: {exc}"
        print(f"  FAIL {step_key}: {exc}")
    finally:
        if ctx1 is not None:
            ctx1.close()
        if ctx2 is not None:
            ctx2.close()


def run_desktop_step(page: Page, results: dict[str, str]) -> None:
    out_dir = OUT_DIR / "1280"

    def desktop_home() -> None:
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#loginView", timeout=10_000)
        page.wait_for_selector(".desk-aside", timeout=10_000)
        page.wait_for_selector(".phone-frame", timeout=10_000)
        sign_in(page)
        page.wait_for_selector("#screenHome .home-greeting", timeout=10_000)
        page.wait_for_selector("#screenHome .home-slogan", timeout=10_000)
        page.wait_for_selector("text=Pay today. Earn tomorrow.", timeout=10_000)
        page.wait_for_selector("text=Demo: type your name and continue", timeout=10_000)
        page.wait_for_timeout(2_000)
        page.wait_for_function(
            """() => {
              const aside = document.querySelector(".desk-aside");
              return aside && getComputedStyle(aside).display !== "none";
            }""",
            timeout=10_000,
        )

    run_step(
        results,
        "1280/14_desktop_1280",
        page,
        out_dir,
        "14_desktop_1280",
        desktop_home,
        full_page=False,
    )


def main() -> int:
    results: dict[str, str] = {}
    print("Starting Woza screenshot run...", flush=True)
    prepare_output_dir()
    print(f"Cleared {OUT_DIR.relative_to(ROOT)} (fresh run only)", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for width, height, label in VIEWPORTS:
            print(f"\n--- Viewport {width}x{height} -> screenshots/{label}/ ---", flush=True)
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=3,
                user_agent=IPHONE_14_UA,
                is_mobile=True,
                has_touch=True,
            )

            page = context.new_page()
            page.set_default_navigation_timeout(20_000)
            page.set_default_timeout(15_000)

            out_dir = OUT_DIR / label
            run_all_steps(page, out_dir, results, label)

            context.close()

        print("\n--- Viewport 1280x800 -> screenshots/1280/ ---", flush=True)
        desktop_ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2,
            is_mobile=False,
            has_touch=False,
        )
        desktop_page = desktop_ctx.new_page()
        desktop_page.set_default_navigation_timeout(20_000)
        desktop_page.set_default_timeout(15_000)
        run_desktop_step(desktop_page, results)
        desktop_ctx.close()

        print("\n--- Isolation: two browser contexts ---", flush=True)
        run_isolation_step(browser, results)

        browser.close()

    if OUT_DIR.exists():
        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
            for png in sorted(OUT_DIR.rglob("*.png")):
                rel = png.relative_to(OUT_DIR)
                zf.write(png, arcname=f"screenshots/{rel.as_posix()}")
        print(f"\nWrote {ZIP_PATH}")

    for width, height, label in VIEWPORTS + [(1280, 800, "1280")]:
        prefix = label
        steps = [k for k in results if k.startswith(f"{prefix}/")]
        passed = sum(1 for k in steps if results[k] == "pass")
        failed = len(steps) - passed
        print(f"\n{label} ({width}x{height}): {passed} passed, {failed} failed (of {len(steps)} steps)")

    passed_total = sum(1 for v in results.values() if v == "pass")
    failed_total = len(results) - passed_total
    print(f"\nOverall: {passed_total} passed, {failed_total} failed (of {len(results)} steps)")
    for step_key, status in sorted(results.items()):
        mark = "PASS" if status == "pass" else "FAIL"
        print(f"  [{mark}] {step_key}" + ("" if status == "pass" else f" — {status}"))

    return 1 if failed_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
