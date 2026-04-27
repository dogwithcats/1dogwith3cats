#!/usr/bin/env python3
"""Capture a full Grafana dashboard screenshot using Playwright.

Usage:
  python grafana_screenshot.py \
    --url 'http://127.0.0.1:3000/d/xxx/dashboard?orgId=1' \
    --output dashboard.png
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture full-page Grafana dashboard screenshot")
    parser.add_argument("--url", required=True, help="Full Grafana dashboard URL")
    parser.add_argument("--output", default="dashboard_full.png", help="Output image path")
    parser.add_argument("--width", type=int, default=1920, help="Viewport width")
    parser.add_argument("--height", type=int, default=1080, help="Viewport height")
    parser.add_argument("--wait-seconds", type=float, default=8.0, help="Extra wait time after load")
    parser.add_argument("--timeout", type=int, default=60000, help="Page timeout in ms")
    parser.add_argument("--username", default=None, help="Grafana username (if login required)")
    parser.add_argument("--password", default=None, help="Grafana password (if login required)")
    parser.add_argument(
        "--login-url",
        default=None,
        help="Optional login URL. If omitted, tries current page for login form.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    return parser.parse_args()


def maybe_login(page, args: argparse.Namespace) -> None:
    if not args.username or not args.password:
        return

    if args.login_url:
        page.goto(args.login_url, wait_until="domcontentloaded", timeout=args.timeout)

    user_candidates = [
        "input[name='user']",
        "input[name='username']",
        "input[id='user']",
        "input[type='text']",
    ]
    pass_candidates = [
        "input[name='password']",
        "input[id='password']",
        "input[type='password']",
    ]

    user_selector = next((s for s in user_candidates if page.locator(s).count() > 0), None)
    pass_selector = next((s for s in pass_candidates if page.locator(s).count() > 0), None)

    if not user_selector or not pass_selector:
        return

    page.fill(user_selector, args.username)
    page.fill(pass_selector, args.password)

    submit_candidates = [
        "button[type='submit']",
        "button:has-text('Log in')",
        "button:has-text('登录')",
    ]
    submit_selector = next((s for s in submit_candidates if page.locator(s).count() > 0), None)
    if submit_selector:
        page.click(submit_selector)
        page.wait_for_load_state("networkidle", timeout=args.timeout)


def capture(args: argparse.Namespace) -> Path:
    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=1,
            ignore_https_errors=True,
        )
        page = context.new_page()

        page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout)
        maybe_login(page, args)
        page.goto(args.url, wait_until="networkidle", timeout=args.timeout)

        # Grafana panels can continue rendering after network is idle.
        time.sleep(max(0.0, args.wait_seconds))

        # Hide floating helper widgets/feedback buttons for cleaner screenshot.
        page.add_style_tag(
            content="""
                [aria-label='Open AI Assistant'],
                [aria-label='Feedback'],
                .help-widget,
                .intercom-lightweight-app {
                    display: none !important;
                }
            """
        )

        page.screenshot(path=str(out_path), full_page=True)
        context.close()
        browser.close()

    return out_path


def main() -> None:
    args = parse_args()
    try:
        output = capture(args)
        print(f"Screenshot saved: {output}")
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"Timeout while loading dashboard: {exc}") from exc


if __name__ == "__main__":
    main()
