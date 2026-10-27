#!/usr/bin/env python3
"""Sign in to ChatGPT/Gemini on Granite headless Chromium from this laptop (CDP over SSH tunnel)."""

from __future__ import annotations

import argparse
import sys

ACCOUNTS = {
    "chatgpt": ("http://127.0.0.1:19230", "https://chatgpt.com/", "info@autowww.org"),
    "chatgpt-primary": ("http://127.0.0.1:19230", "https://chatgpt.com/", "info@autowww.org"),
    "gemini": ("http://127.0.0.1:19231", "https://gemini.google.com/", "leonid.zvyagintsev@gmail.com"),
    "gemini-primary": (
        "http://127.0.0.1:19231",
        "https://gemini.google.com/",
        "leonid.zvyagintsev@gmail.com",
    ),
}


def _try_prefill_email(page, email: str) -> None:
    if not email:
        return
    for sel in (
        "input[type='email']",
        "input[name='identifier']",
        "input#identifierId",
        "input[type='text'][autocomplete='username']",
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=2000):
                loc.fill(email, timeout=5000)
                page.keyboard.press("Enter")
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "account",
        choices=sorted(ACCOUNTS.keys()),
        help="Which Granite Open WebUI account profile to authenticate",
    )
    args = parser.parse_args()
    cdp_url, start_url, login_email = ACCOUNTS[args.account]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install 'forge-lcdl[playwright]' && playwright install chromium", file=sys.stderr)
        return 2

    print(f"CDP {cdp_url} → {start_url}")
    print("Playwright Inspector will open on this laptop. Sign in, then close Inspector or press Resume.")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=30_000)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3000)
        _try_prefill_email(page, login_email)
        print(f"Complete sign-in for {login_email} in Inspector, then Resume.")
        try:
            page.pause()
        except Exception:
            pass
        # Leave remote headless Edge running; disconnect Playwright only.
        try:
            browser.disconnect()
        except Exception:
            pass

    bridge_port = "9240" if "chatgpt" in args.account else "9241"
    print(f"Done. Session saved in Granite profile. Test bridge: curl http://127.0.0.1:{bridge_port}/health on granite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
