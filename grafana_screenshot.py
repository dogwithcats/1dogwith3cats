#!/usr/bin/env python3
"""Capture single or batch Grafana dashboard screenshots using Playwright."""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

LOGIN_URL_RE = re.compile(r"/login(?:$|[?#])")


def normalize_credential(value: str | None) -> str | None:
    """Trim accidental wrapping quotes from shell input (common on Windows cmd)."""
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unknown"


def infer_output_name_from_url(url: str) -> str:
    qs = parse_qs(urlparse(url).query)
    name = sanitize_filename_part(qs.get("var-name", ["name"])[0])
    node = sanitize_filename_part(qs.get("var-node", ["node"])[0])
    return f"{name}_{node}.png"


def set_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query[key] = [value]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def load_nodes(args: argparse.Namespace) -> list[str]:
    nodes: list[str] = []

    if args.nodes:
        nodes.extend([n.strip() for n in args.nodes.split(",") if n.strip()])

    if args.nodes_file:
        content = Path(args.nodes_file).read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            nodes.append(line)

    deduped = []
    seen = set()
    for node in nodes:
        if node not in seen:
            deduped.append(node)
            seen.add(node)
    return deduped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture full-page Grafana dashboard screenshot")
    parser.add_argument("--url", required=True, help="Full Grafana dashboard URL")
    parser.add_argument("--output", default=None, help="Single mode output path (default: var-name_var-node.png)")
    parser.add_argument("--output-dir", default=".", help="Batch mode output directory")
    parser.add_argument("--nodes", default=None, help="Batch node list, comma-separated (e.g. 10.0.0.1:9100,10.0.0.2:9100)")
    parser.add_argument("--nodes-file", default=None, help="Batch node file, one node per line")
    parser.add_argument("--export-urls", default=None, help="Export generated dashboard URLs to a text file")
    parser.add_argument("--failed-file", default="failed_nodes.txt", help="Write failed node+reason report in batch mode")
    parser.add_argument("--width", type=int, default=1920, help="Viewport width")
    parser.add_argument("--height", type=int, default=1080, help="Viewport height")
    parser.add_argument("--wait-seconds", type=float, default=8.0, help="Extra wait time after load")
    parser.add_argument("--timeout", type=int, default=120000, help="Page timeout in ms")
    parser.add_argument("--retries", type=int, default=2, help="Retries per node when timeout/error occurs")
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


def robust_goto(page: Page, url: str, timeout: int) -> None:
    """Navigate with fallback wait strategies to reduce flaky timeouts."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return
    except PlaywrightTimeoutError:
        pass

    # Fallback: commit waits only until first byte of response.
    page.goto(url, wait_until="commit", timeout=timeout)


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


def ensure_dashboard_loaded(page: Page, args: argparse.Namespace, target_url: str) -> None:
    robust_goto(page, target_url, args.timeout)

    if is_login_page(page):
        if not args.username or not args.password:
            raise RuntimeError("当前页面是 Grafana 登录页。请提供 --username 和 --password。")

        if args.login_url:
            robust_goto(page, args.login_url, args.timeout)

        perform_login(page, args.username, args.password, args.timeout)
        robust_goto(page, target_url, args.timeout)

    if is_login_page(page):
        raise RuntimeError(f"登录后仍停留在登录页（当前URL: {page.url}）。请检查用户名密码、权限或 Grafana 认证方式。")


def capture_single_with_page(page: Page, args: argparse.Namespace, target_url: str, output: Path) -> Path:
    ensure_dashboard_loaded(page, args, target_url)

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

    output.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output), full_page=True)
    return output


def build_batch_targets(args: argparse.Namespace) -> list[tuple[str, str, Path]]:
    nodes = load_nodes(args)
    if not nodes:
        return []

    output_dir = Path(args.output_dir).expanduser().resolve()
    targets: list[tuple[str, str, Path]] = []

    for node in nodes:
        url = set_query_param(args.url, "var-node", node)
        file_name = infer_output_name_from_url(url)
        targets.append((node, url, output_dir / file_name))

    return targets


def run_batch(args: argparse.Namespace) -> tuple[list[Path], list[str]]:
    targets = build_batch_targets(args)
    if not targets:
        return [], []

    if args.export_urls:
        export_path = Path(args.export_urls).expanduser().resolve()
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("\n".join(url for _, url, _ in targets) + "\n", encoding="utf-8")
        print(f"URLs exported: {export_path}")

    outputs: list[Path] = []
    failed: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=1,
            ignore_https_errors=True,
        )
        page = context.new_page()

        for index, (node, url, out) in enumerate(targets, start=1):
            last_error = ""
            success = False

            for attempt in range(1, max(1, args.retries) + 1):
                try:
                    saved = capture_single_with_page(page, args, url, out)
                    outputs.append(saved)
                    print(f"[{index}/{len(targets)}] OK   {node} -> {saved}")
                    success = True
                    break
                except (PlaywrightTimeoutError, RuntimeError) as exc:
                    last_error = str(exc)
                    print(f"[{index}/{len(targets)}] RETRY {attempt}/{args.retries} {node} failed: {last_error}")
                    page.goto("about:blank")

            if not success:
                failed_line = f"{node}\t{last_error}"
                failed.append(failed_line)
                print(f"[{index}/{len(targets)}] FAIL {node} -> {last_error}")

        context.close()
        browser.close()

    if failed and args.failed_file:
        failed_path = Path(args.failed_file).expanduser().resolve()
        failed_path.parent.mkdir(parents=True, exist_ok=True)
        failed_path.write_text("\n".join(failed) + "\n", encoding="utf-8")
        print(f"Failed node report: {failed_path}")

    return outputs, failed


def run_single(args: argparse.Namespace) -> Path:
    output = args.output or infer_output_name_from_url(args.url)
    out_path = Path(output).expanduser().resolve()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=1,
            ignore_https_errors=True,
        )
        page = context.new_page()

        saved = capture_single_with_page(page, args, args.url, out_path)

        context.close()
        browser.close()

    return saved


def main() -> None:
    args = parse_args()
    args.username = normalize_credential(args.username)
    args.password = normalize_credential(args.password)

    try:
        if load_nodes(args):
            outputs, failed = run_batch(args)
            if not outputs and failed:
                raise SystemExit("批量截图全部失败，请查看 failed_nodes.txt 和超时参数（--timeout）。")
            print(f"Batch done, success: {len(outputs)}, failed: {len(failed)}")
        else:
            output = run_single(args)
            print(f"Screenshot saved: {output}")
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"Timeout while loading dashboard: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
