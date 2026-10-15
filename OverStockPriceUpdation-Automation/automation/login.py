"""Overstock Edge login helpers (Playwright async)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

from playwright.async_api import Page

try:
    from dotenv import dotenv_values, load_dotenv
except ImportError:
    dotenv_values = None
    load_dotenv = None

from automation import settings
from automation.constants import (
    URLS,
)
from automation.selectors import (
    SELECTORS,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_ENV_CANDIDATES = [
    _ROOT / ".env",
    Path(r"C:\Users\hi\Desktop\Project\Giga_Backend\.env"),
]


def _env_path() -> Path | None:
    for path in _ENV_CANDIDATES:
        if path.is_file():
            return path
    return None


def _load_project_env() -> None:
    path = _env_path()
    if load_dotenv is None or path is None:
        return
    load_dotenv(dotenv_path=path, override=False)


def _normalize_env_value(raw: str | None) -> str:
    value = (raw or "").replace("\r", "").strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def _read_env(key: str) -> str:
    """Prefer this project's .env, then Giga_Backend/.env, then process env."""
    _load_project_env()
    path = _env_path()
    if dotenv_values is not None and path is not None:
        try:
            file_vals = dict(dotenv_values(path))
            from_file = _normalize_env_value(file_vals.get(key))
            if from_file:
                return from_file
        except Exception:
            pass
    return _normalize_env_value(os.getenv(key))


def get_automation_credentials() -> Tuple[str, str]:
    """
    Edge UI login for price Playwright automation.

    Uses OVERSTOCK_USERNAME / OVERSTOCK_PASSWORD from Giga_Backend/.env
    (same keys as OASIS API). If username has no domain\\ prefix, prepends
    EDGE_LOGIN_DOMAIN (default supplieroasis.com) for ADFS login.
    """
    user_key = str(getattr(settings, "ENV_USERNAME", "OVERSTOCK_USERNAME") or "").strip()
    pass_key = str(getattr(settings, "ENV_PASSWORD", "OVERSTOCK_PASSWORD") or "").strip()
    username = _read_env(user_key) or _read_env("Username")
    password = _read_env(pass_key) or _read_env("Password")
    if not username or not password:
        raise RuntimeError(
            "Missing Overstock credentials. Set OVERSTOCK_USERNAME and OVERSTOCK_PASSWORD, "
            "or Username and Password, in .env."
        )
    if "\\" not in username and "/" not in username:
        domain = str(getattr(settings, "EDGE_LOGIN_DOMAIN", "supplieroasis.com") or "").strip()
        if domain:
            username = f"{domain}\\{username}"
    return username, password


def _is_edge_app_url(url_string: str) -> bool:
    try:
        return urlparse(url_string).hostname == "edge.supplieroasis.com"
    except Exception:
        return False


async def login_to_overstock(
    page: Page,
    log: Optional[Callable[[str], None]] = None,
    *,
    account_key: Optional[str] = None,
) -> None:
    _ = account_key  # OASIS account_key unused — automation has its own env creds
    log_fn = log or logger.info
    username, password = get_automation_credentials()

    log_fn("Opening Overstock login page")
    await page.goto(URLS["login"], wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_selector(SELECTORS["userNameInput"], timeout=60_000)

    await page.fill(SELECTORS["userNameInput"], username)
    await page.fill(SELECTORS["passwordInput"], password)

    log_fn("Submitting login")
    await page.click(SELECTORS["submitButton"])

    log_fn("Waiting for Edge dashboard (domcontentloaded)…")
    await page.wait_for_url(
        lambda url: _is_edge_app_url(str(url)),
        timeout=180_000,
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(2500)

    if not _is_edge_app_url(page.url):
        err = ""
        try:
            err = (await page.locator("#errorText").text_content()) or ""
        except Exception:
            pass
        raise RuntimeError(
            f"Login did not reach Edge app (url={page.url})"
            + (f": {err.strip()}" if err.strip() else "")
        )

    log_fn(f"Login successful — {page.url}")


async def goto_edge(
    page: Page,
    url: str,
    log: Optional[Callable[[str], None]] = None,
    label: Optional[str] = None,
) -> None:
    log_fn = log or logger.info
    log_fn(f"Navigating to {label or url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=180_000)
    await page.wait_for_timeout(4000)
    if not _is_edge_app_url(page.url):
        raise RuntimeError(f"Expected Edge app, got: {page.url}")
