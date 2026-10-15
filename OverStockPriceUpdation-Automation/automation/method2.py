"""Method 2 — filter → export → edit sheet → import to Overstock (keep latest sheets only)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from automation.browser import (
    assert_not_cancelled,
    close_browser,
    launch_browser,
    prepare_method2_sheets_dir,
)
from automation.constants import (
    FILTER_PREFIX,
    URLS,
)
from automation.edit_sheet import (
    edit_cost_export_sheet,
)
from automation.export_logs import (
    wait_and_download_latest_export,
)
from automation.login import (
    goto_edge,
    login_to_overstock,
)
from automation.pricing_actions import (
    export_search_results,
    filter_supplier_sku_contains,
)
from automation.selectors import (
    SELECTORS,
)

logger = logging.getLogger(__name__)


async def _import_edited_sheet(page: Any, file_path: str, log: Callable[[str], None]) -> None:
    await goto_edge(page, URLS["manageCost"], log, "Manage Cost for Import")
    log("Waiting 4s — Manage Cost page load")
    await page.wait_for_timeout(4000)

    log("Clicking Import")
    await page.get_by_role("button", name="Import").first.click()
    await page.get_by_text("File Upload").wait_for(timeout=60_000)

    job_name = f"HNF-price-{datetime.now(timezone.utc).isoformat().replace(':', '-').replace('.', '-')}"
    await page.locator(SELECTORS["importModalJobName"]).fill(job_name)

    log(f"Uploading sheet: {file_path}")
    await page.locator(SELECTORS["importModalFileInput"]).set_input_files(file_path)

    upload_btn = page.locator(SELECTORS["importModalUploadButton"])
    await upload_btn.wait_for(state="visible")
    try:
        await page.wait_for_function(
            """(sel) => {
              const el = document.querySelector(sel);
              return el && !el.classList.contains('disabled') && !el.disabled;
            }""",
            SELECTORS["importModalUploadButton"],
            timeout=60_000,
        )
    except Exception:
        pass

    await upload_btn.click(force=True)
    log("Waiting 5s — import upload to process")
    await page.wait_for_timeout(5000)
    log("Import upload clicked")


async def run_method2(
    *,
    price_by_sku: Mapping[str, float],
    headed: Optional[bool] = None,
    headless: Optional[bool] = None,
    filter: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    import_sheet: bool = False,
) -> Dict[str, Any]:
    log_fn = log or logger.info
    if not price_by_sku:
        raise ValueError("price_by_sku map is required")

    filt = filter or FILTER_PREFIX
    # Delete previous Method2 sheets, then download + edit into the same folder.
    run_dir = prepare_method2_sheets_dir()
    log_fn(f"Method 2 sheets folder ready (old files cleared): {run_dir}")

    browser = None
    try:
        assert_not_cancelled(is_cancelled)
        launched = await launch_browser(
            headed=headed, headless=headless, downloads_dir=run_dir, log=log_fn
        )
        browser = launched["browser"]
        page = launched["page"]

        assert_not_cancelled(is_cancelled)
        await login_to_overstock(page, log_fn)

        assert_not_cancelled(is_cancelled)
        await goto_edge(page, URLS["manageCost"], log_fn, "Manage Cost")
        log_fn("Waiting 5s — Manage Cost page to load fully")
        await page.wait_for_timeout(5000)
        await page.locator(SELECTORS["exportButton"]).wait_for(state="visible", timeout=180_000)

        assert_not_cancelled(is_cancelled)
        await filter_supplier_sku_contains(page, filt, log_fn)

        assert_not_cancelled(is_cancelled)
        await export_search_results(page, log_fn)

        assert_not_cancelled(is_cancelled)
        downloaded_path = await wait_and_download_latest_export(
            page,
            log_fn,
            is_cancelled=is_cancelled,
            max_wait_ms=45 * 60 * 1000,
            downloads_dir=run_dir,
        )

        edited_path = str(run_dir / f"edited_{Path(downloaded_path).name}")

        assert_not_cancelled(is_cancelled)
        edit_result = edit_cost_export_sheet(downloaded_path, edited_path, price_by_sku, log_fn)

        imported = False
        if import_sheet:
            assert_not_cancelled(is_cancelled)
            await _import_edited_sheet(page, edited_path, log_fn)
            imported = True
            log_fn("Import upload clicked")
        else:
            log_fn(f"Import skipped. Edited sheet saved: {edited_path}")

        log_fn("Method 2 complete")
        pushed = int(edit_result.get("updated") or 0) if imported else 0
        return {
            "ok": True,
            "method": 2,
            "action": "push" if imported else "generate",
            "downloadedPath": downloaded_path,
            "editedPath": edited_path,
            "sheetsDir": str(run_dir),
            "pushed": pushed,
            "imported": imported,
            **edit_result,
            "summary": {
                "action": "push" if imported else "generate",
                "method": 2,
                "pushed": pushed,
                "updated": edit_result.get("updated"),
                "missingCount": edit_result.get("missingCount"),
                "sheetsDir": str(run_dir),
            },
        }
    finally:
        await close_browser(browser)
        log_fn(f"Method 2 latest sheets kept (previous run replaced): {run_dir}")
