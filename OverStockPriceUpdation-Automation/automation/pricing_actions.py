"""Manage Cost filter + export actions (Playwright async)."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from playwright.async_api import Page

from automation.selectors import (
    SELECTORS,
)

logger = logging.getLogger(__name__)


async def _sleep(page: Page, ms: int, log: Optional[Callable[[str], None]], reason: Optional[str]) -> None:
    if callable(log) and reason:
        log(f"Waiting {round(ms / 1000)}s — {reason}")
    await page.wait_for_timeout(ms)


async def _reveal_vendor_sku_column(page: Page) -> None:
    await page.evaluate(
        """() => {
      const header =
        document.querySelector('.MuiDataGrid-columnHeader[data-field="vendorSku"]') ||
        document.querySelector('[role="columnheader"][data-field="vendorSku"]') ||
        document.querySelector('.MuiDataGrid-columnHeader[aria-label="Supplier SKU"]');
      if (!header) return false;
      header.scrollIntoView({ block: 'nearest', inline: 'center' });
      const scroller =
        header.closest('.MuiDataGrid-virtualScroller') ||
        document.querySelector('.MuiDataGrid-virtualScroller') ||
        document.querySelector('.MuiDataGrid-main');
      if (scroller && header) {
        const scrollerRect = scroller.getBoundingClientRect();
        const headerRect = header.getBoundingClientRect();
        const delta =
          headerRect.left - scrollerRect.left - scrollerRect.width / 2 + headerRect.width / 2;
        scroller.scrollLeft += delta;
      }
      return true;
    }"""
    )
    await page.wait_for_timeout(800)


async def filter_supplier_sku_contains(
    page: Page,
    value: str,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    log_fn = log or logger.info
    log_fn(f"Filtering Supplier SKU Contains: {value}")

    await page.locator(".MuiDataGrid-root, [role=\"grid\"]").first.wait_for(
        state="visible", timeout=120_000
    )

    input_candidates = [
        '.MuiDataGrid-columnHeader[data-field="vendorSku"] .MuiDataGrid-columnHeaderFilterInput input',
        '[role="columnheader"][data-field="vendorSku"] .MuiDataGrid-columnHeaderFilterInput input',
        '.MuiDataGrid-columnHeader[data-field="vendorSku"] input',
        '[role="columnheader"][data-field="vendorSku"] input',
        '.MuiDataGrid-columnHeader[aria-label="Supplier SKU"] input',
        '[role="columnheader"][aria-label="Supplier SKU"] input',
    ]

    input_loc = None
    deadline_ms = 120_000
    elapsed = 0
    last_err: Optional[Exception] = None

    while elapsed < deadline_ms:
        await _reveal_vendor_sku_column(page)
        for sel in input_candidates:
            loc = page.locator(sel).first
            try:
                count = await loc.count()
            except Exception as exc:
                last_err = exc
                continue
            if not count:
                continue
            try:
                await loc.wait_for(state="attached", timeout=2000)
                try:
                    await loc.scroll_into_view_if_needed()
                except Exception:
                    pass
                await loc.click(force=True, timeout=5000)
                input_loc = loc
                break
            except Exception as exc:
                last_err = exc
        if input_loc:
            break
        await page.evaluate(
            """() => {
          const scroller =
            document.querySelector('.MuiDataGrid-virtualScroller') ||
            document.querySelector('.MuiDataGrid-scrollbar--horizontal');
          if (scroller) scroller.scrollLeft += 180;
        }"""
        )
        await page.wait_for_timeout(500)
        elapsed += 500

    if not input_loc:
        msg = getattr(last_err, "message", None) or str(last_err or "none")
        raise RuntimeError(f"Could not find Supplier SKU filter input (Contains). Last error: {msg}")

    log_fn("Supplier SKU filter box found — typing value")
    await input_loc.click(click_count=3, force=True)
    await input_loc.fill("")
    await input_loc.fill(value)
    typed = ""
    try:
        typed = await input_loc.input_value()
    except Exception:
        pass
    if typed != value:
        log_fn(f'fill() left "{typed}" — typing via keyboard')
        await input_loc.click(force=True)
        await page.keyboard.press("Control+A")
        await page.keyboard.type(value, delay=40)

    await input_loc.press("Enter")
    await _sleep(page, 4000, log_fn, "filter results to load")
    final_val = ""
    try:
        final_val = await input_loc.input_value()
    except Exception:
        pass
    log_fn(f'Supplier SKU filter set to "{final_val or value}"')


async def export_search_results(
    page: Page,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    import time

    log_fn = log or logger.info
    log_fn("Waiting for Export button…")
    await page.locator(SELECTORS["exportButton"]).wait_for(state="visible", timeout=180_000)
    await _sleep(page, 2000, log_fn, "UI settle before Export")

    log_fn("Clicking Export")
    await page.locator(SELECTORS["exportButton"]).click()

    by_id = page.locator(SELECTORS["exportSearchResultsBtn"])
    by_text = page.get_by_role("menuitem", name="Export Search Results").or_(
        page.get_by_text("Export Search Results")
    )
    menu_item = by_id.or_(by_text).first

    await menu_item.wait_for(state="visible", timeout=60_000)
    await _sleep(page, 1000, log_fn, "dropdown open")

    log_fn("Choosing Export Search Results")
    export_started_at = int(time.time() * 1000)
    await menu_item.click()
    await _sleep(page, 8000, log_fn, "export job to be created on server")
    return {"exportStartedAt": export_started_at}
