"""Playwright browser launch / close for Overstock price automation."""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from playwright.async_api import Browser, async_playwright

from automation import settings

logger = logging.getLogger(__name__)

# Edited Overstock export is saved in the project output folder.
DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "output"
METHOD2_SHEETS_DIR = DOWNLOADS_DIR


def create_temp_downloads_dir() -> Path:
    """Ephemeral OS temp dir (used by pull/sync which still cleans up)."""
    return Path(tempfile.mkdtemp(prefix="overstock_price_sheets_"))


def create_run_downloads_dir(*, prefix: str = "method2") -> Path:
    """Per-run folder under price/downloads (legacy / other callers)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = DOWNLOADS_DIR / f"{prefix}_{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_method2_sheets_dir() -> Path:
    """Wipe previous Method2 sheets, then return a fresh folder for this download."""
    if METHOD2_SHEETS_DIR.exists():
        shutil.rmtree(METHOD2_SHEETS_DIR, ignore_errors=True)
    METHOD2_SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    return METHOD2_SHEETS_DIR


def cleanup_downloads_dir(path: Optional[Path]) -> None:
    if path is None:
        return
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.exception("Failed to cleanup Overstock price temp downloads dir %s", path)

_active_browser: Optional[Browser] = None
_playwright_cm: Any = None


def get_active_browser() -> Optional[Browser]:
    return _active_browser


async def force_close_active_browser() -> bool:
    global _active_browser, _playwright_cm
    if not _active_browser:
        return False
    try:
        await _active_browser.close()
    except Exception:
        pass
    _active_browser = None
    if _playwright_cm is not None:
        try:
            await _playwright_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _playwright_cm = None
    return True


def _resolve_headless(
    *,
    headed: Optional[bool] = None,
    headless: Optional[bool] = None,
) -> bool:
    if isinstance(headless, bool):
        return headless
    if isinstance(headed, bool):
        return not headed
    return bool(getattr(settings, "AUTOMATION_HEADLESS", False))


async def launch_browser(
    *,
    headed: Optional[bool] = None,
    headless: Optional[bool] = None,
    slow_mo_ms: Optional[int] = None,
    downloads_dir: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Launch Chromium via Playwright async_api."""
    global _active_browser, _playwright_cm

    log_fn = log or logger.info
    is_headless = _resolve_headless(headed=headed, headless=headless)
    is_headed = not is_headless
    slow_mo = (
        int(slow_mo_ms)
        if slow_mo_ms is not None
        else (int(getattr(settings, "AUTOMATION_SLOW_MO_MS", 100) or 100) if is_headed else 0)
    )

    ddir = Path(downloads_dir) if downloads_dir else DOWNLOADS_DIR
    ddir.mkdir(parents=True, exist_ok=True)
    log_fn(
        "Launching Edge headless (no browser window)"
        if is_headless
        else "Launching Edge full window"
    )

    _playwright_cm = async_playwright()
    pw = await _playwright_cm.__aenter__()
    # Installed Edge, not Playwright's Chromium-for-Testing build.
    browser = await pw.chromium.launch(
        channel="msedge",
        headless=is_headless,
        slow_mo=slow_mo,
        args=["--start-maximized"] if is_headed else [],
        ignore_default_args=["--enable-automation"] if is_headed else None,
    )
    _active_browser = browser

    context = await browser.new_context(
        accept_downloads=True,
        no_viewport=True if is_headed else None,
        viewport=None if is_headed else {"width": 1400, "height": 900},
    )
    page = await context.new_page()
    page.set_default_timeout(60_000)

    if is_headed:
        try:
            await page.bring_to_front()
            session = await context.new_cdp_session(page)
            window = await session.send("Browser.getWindowForTarget")
            await session.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {"windowState": "maximized"},
                },
            )
        except Exception:
            pass

    return {
        "browser": browser,
        "context": context,
        "page": page,
        "headed": is_headed,
        "headless": is_headless,
        "downloadsDir": str(ddir),
        "downloadsPath": ddir,
        "playwright": pw,
    }


async def close_browser(browser: Optional[Browser] = None) -> None:
    global _active_browser, _playwright_cm
    try:
        if browser:
            await browser.close()
    except Exception:
        pass
    if _active_browser is browser or browser is None:
        _active_browser = None
    if _playwright_cm is not None:
        try:
            await _playwright_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _playwright_cm = None


class CancelledError(Exception):
    code = "CANCELLED"


def assert_not_cancelled(
    is_cancelled: Optional[Callable[[], bool]],
    message: str = "Automation stopped by user",
) -> None:
    if callable(is_cancelled) and is_cancelled():
        err = CancelledError(message)
        raise err
