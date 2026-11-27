"""Run one web-UI prompt in a fresh process.

Playwright's sync API does not complete reliably on the uvicorn worker thread.
A child process has a normal main thread, which is what the connectors expect.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from forge_web_bridge.catalog import resolve_requested_model


def _variant(provider: str, base_id: str, model: str) -> dict[str, Any] | None:
    return resolve_requested_model(provider, base_id, model)


def _log(msg: str) -> None:
    try:
        with open("/tmp/forge-web-bridge-run.log", "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
            fh.flush()
    except Exception:
        pass


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.flush()
    # Playwright teardown over an SSH CDP tunnel can block forever after the
    # answer is already on stdout. Exit without running it.
    os._exit(0)


def _fail(status: int, detail: str, *, retry_after: int | None = None) -> None:
    payload: dict[str, Any] = {"ok": False, "status": status, "detail": detail}
    if retry_after is not None:
        payload["retry_after"] = int(retry_after)
    _emit(payload)


def _finish_provider(result: Any) -> None:
    from forge_lcdl.result import Err
    from forge_lcdl.playwright.connectors.usage_limit import parse_limit_error

    if isinstance(result, Err):
        message = str(result.error.message or "")
        hit = parse_limit_error(message)
        if hit is not None or getattr(result.error, "kind", "") == "rate_limited":
            _fail(429, message, retry_after=hit.retry_after_s if hit is not None else 3600)
        _fail(502, message)
    _emit({"ok": True, "text": str(result.value or "").strip()})


def _chatgpt_cloudflare_title(cdp_url: str) -> str:
    """Read the tab list. A Cloudflare interstitial must not enter the long connect path."""
    import urllib.request

    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/list", timeout=3) as response:
            rows = json.loads(response.read().decode())
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "")
        url = str(row.get("url") or "")
        if "chatgpt.com" in url and "just a moment" in title.lower():
            return title
    return ""


def run(payload: dict[str, Any]) -> int:
    prompt = str(payload.get("prompt") or "").strip()
    provider = str(payload.get("provider") or "")
    cdp_url = str(payload.get("cdp_url") or "")
    model = str(payload.get("model") or "")
    base_id = str(payload.get("model_id") or "")
    if not prompt:
        _fail(400, "messages must include a user prompt")
    if payload.get("continue_thread"):
        os.environ["CHATGPT_KEEP_CONVERSATION"] = "1"
    else:
        os.environ.pop("CHATGPT_KEEP_CONVERSATION", None)
    variant = _variant(provider, base_id, model)
    _log(f"start provider={provider} model={model}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _fail(503, "playwright not installed on the bridge host")

    from forge_lcdl.result import Err

    try:
        with sync_playwright() as pw:
            if provider == "chatgpt":
                from forge_lcdl.playwright.connectors.chatgpt import connect_chatgpt_tab, send_chatgpt_prompt

                stuck = _chatgpt_cloudflare_title(cdp_url)
                if stuck:
                    _fail(503, "ChatGPT is still on the Cloudflare check, so this turn cannot join the conversation.")
                _log("chatgpt connect")
                attached = connect_chatgpt_tab(pw, cdp_url)
                _log(
                    "chatgpt connect err " + attached.error.message
                    if isinstance(attached, Err)
                    else "chatgpt connected " + str(getattr(attached.value.page, "url", ""))[:100]
                )
                if isinstance(attached, Err):
                    _fail(503, attached.error.message)
                sess = attached.value
                page_url = str(getattr(sess.page, "url", "") or "")
                if "challenges.cloudflare.com" in page_url or page_url.startswith("https://chatgpt.com/cdn-cgi/"):
                    _fail(
                        503,
                        "ChatGPT Cloudflare challenge on Granite. The laptop Edge session cannot be reused from this network.",
                    )
                try:
                    title = str(sess.page.title() or "")
                except Exception:
                    title = ""
                if "just a moment" in title.lower():
                    _fail(503, "ChatGPT is still on the Cloudflare check, so this turn cannot join the conversation.")
                if not payload.get("continue_thread"):
                    from forge_lcdl.playwright.connectors.chatgpt import leave_chatgpt_thread

                    leave_chatgpt_thread(sess.page)
                if variant:
                    from forge_lcdl.playwright.connectors.web_ui_models import select_chatgpt_web_model

                    picked = select_chatgpt_web_model(
                        sess.page,
                        label=str(variant.get("label") or variant.get("slug") or ""),
                        match=list(variant.get("match") or []),
                        position=variant.get("position"),
                    )
                    if isinstance(picked, Err):
                        _fail(503, picked.error.message)
                _log("chatgpt send")
                result = send_chatgpt_prompt(sess.page, prompt, min_response_chars=1, timeout_sec=600)
                _log("chatgpt sent")
                if not payload.get("continue_thread") and not isinstance(result, Err):
                    from forge_lcdl.playwright.connectors.chatgpt import delete_chatgpt_thread

                    _log("chatgpt delete " + delete_chatgpt_thread(sess.page))
                _finish_provider(result)

            if provider == "gemini":
                from forge_lcdl.playwright.connectors.gemini import connect_gemini_tab, send_gemini_prompt

                attached = connect_gemini_tab(pw, cdp_url)
                if isinstance(attached, Err):
                    _fail(503, attached.error.message)
                sess = attached.value
                if variant:
                    from forge_lcdl.playwright.connectors.web_ui_models import select_gemini_web_model

                    picked = select_gemini_web_model(
                        sess.page,
                        label=str(variant.get("label") or variant.get("slug") or ""),
                        match=list(variant.get("match") or []),
                    )
                    if isinstance(picked, Err):
                        _fail(503, picked.error.message)
                result = send_gemini_prompt(
                    sess.page,
                    prompt,
                    min_response_chars=1,
                    timeout_sec=600,
                    new_chat=not bool(payload.get("continue_thread")),
                )
                _finish_provider(result)
    except SystemExit:
        raise
    except Exception as exc:
        _fail(503, f"{type(exc).__name__}: {exc}")

    _fail(400, f"unsupported provider: {provider}")


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    run(payload)


if __name__ == "__main__":
    main()
