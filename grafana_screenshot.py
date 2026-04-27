#!/usr/bin/env python3
"""Capture a full Grafana dashboard screenshot using Playwright."""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

LOGIN_URL_RE = re.compile(r"/login(?:$|[?#])")


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
    parser.add_argument("--login-url", default=None, help="Optional explicit login URL")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    return parser.parse_args()


def is_login_page(page: Page) -> bool:
    return bool(LOGIN_URL_RE.search(page.url)) or page.locator("input[type='password']").count() > 0


def first_visible_selector(page: Page, selectors: list[str]) -> str | None:
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0 and locator.first.is_visible():
            return selector
    return None


def perform_login(page: Page, username: str, password: str, timeout: int) -> None:
    user_selector = first_visible_selector(
        page,
        [
            "input[name='user']",
            "input[name='username']",
            "input[id='user']",
            "input[autocomplete='username']",
            "input[type='text']",
        ],
    )
    pass_selector = first_visible_selector(
        page,
        [
            "input[name='password']",
            "input[id='password']",
            "input[autocomplete='current-password']",
            "input[type='password']",
        ],
    )

    if not user_selector or not pass_selector:
        raise RuntimeError("已跳转到登录页，但未找到用户名/密码输入框，请确认 Grafana 登录页结构。")

    page.fill(user_selector, username)
    page.fill(pass_selector, password)

    submit_candidates = [
        "button[type='submit']",
        "button:has-text('Log in')",
        "button:has-text('Sign in')",
        "button:has-text('登录')",
    ]
    submit_selector = first_visible_selector(page, submit_candidates)
    if submit_selector:
        page.click(submit_selector)
    else:
        page.press(pass_selector, "Enter")

    page.wait_for_load_state("networkidle", timeout=timeout)


def ensure_dashboard_loaded(page: Page, args: argparse.Namespace) -> None:
    target = args.url

    page.goto(target, wait_until="domcontentloaded", timeout=args.timeout)

    if is_login_page(page):
        if not args.username or not args.password:
            raise RuntimeError("当前页面是 Grafana 登录页。请提供 --username 和 --password。")

        if args.login_url:
            page.goto(args.login_url, wait_until="domcontentloaded", timeout=args.timeout)
        page.wait_for_load_state("domcontentloaded", timeout=args.timeout)

        perform_login(page, args.username, args.password, args.timeout)

        # 登录后显式回到 dashboard URL，避免停留在 /login 或主页。
        page.goto(target, wait_until="networkidle", timeout=args.timeout)

    # 二次校验：若仍在登录页，给出明确报错，避免误保存登录页截图。
    if is_login_page(page):
        raise RuntimeError("登录后仍停留在登录页，请检查用户名密码、权限或 Grafana 认证方式。")


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

        ensure_dashboard_loaded(page, args)

        # Grafana 面板在 networkidle 后仍可能继续渲染。
        time.sleep(max(0.0, args.wait_seconds))

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
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
