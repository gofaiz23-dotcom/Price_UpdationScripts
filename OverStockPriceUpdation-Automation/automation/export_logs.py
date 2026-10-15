"""Exports/Imports log polling + download for Overstock Cost Export."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import Page

from automation.browser import (
    DOWNLOADS_DIR,
)
from automation.constants import (
    URLS,
)
from automation.selectors import (
    SELECTORS,
)

logger = logging.getLogger(__name__)

DONE_STATUSES = ["COMPLETED", "SUCCESS", "COMPLETE", "SUCCEEDED"]
WAIT_STATUSES = [
    "IN PROGRESS",
    "IN_PROGRESS",
    "PROGRESS",
    "PENDING",
    "PROCESSING",
    "QUEUED",
    "RUNNING",
    "STARTED",
]


def _normalize_status(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().upper()


def _classify_status(row_text: str) -> str:
    t = _normalize_status(row_text)
    for s in WAIT_STATUSES:
        if s in t:
            return "WAIT"
    for s in DONE_STATUSES:
        if s in t:
            return "DONE"
    if re.search(r"\bDOWNLOAD\b", row_text or "", re.I):
        return "DONE"
    return "UNKNOWN"


def _looks_like_export_row(text: str) -> bool:
    t = _normalize_status(text)
    if re.search(r"\bIMPORT\b", t) and not re.search(r"\bEXPORT\b", t):
        return False
    if re.search(r"\bEXPORT\b", t):
        return True
    if re.search(r"COST_EXPORT", text or "", re.I):
        return True
    return False


def _row_identity(text: str, file_name: Optional[str]) -> str:
    if file_name:
        return file_name.upper()
    return _normalize_status(text).replace("  ", " ")[:120]


async def open_export_import_logs(page: Page, log: Callable[[str], None]) -> None:
    log(f"Opening Exports/Imports: {URLS['importExportLogs']}")
    btn = page.locator(SELECTORS["importExportButton"])
    if await btn.count():
        try:
            await btn.click()
        except Exception:
            pass
    await page.goto(URLS["importExportLogs"], wait_until="domcontentloaded", timeout=180_000)
    await page.wait_for_timeout(4000)
    await _wait_for_grid(page, 120_000)
    log(f"Exports/Imports page ready — url={page.url}")


async def _wait_for_grid(page: Page, timeout_ms: int = 90_000) -> None:
    grid = page.locator(
        ", ".join(
            [
                ".MuiDataGrid-root",
                ".MuiDataGrid-virtualScroller",
                '[role="grid"]',
                '[data-field="logsResults"]',
                ".MuiDataGrid-row",
                '[role="row"][data-id]',
                "[data-rowindex]",
            ]
        )
    )
    try:
        await grid.first.wait_for(state="attached", timeout=timeout_ms)
    except Exception:
        pass
    await page.wait_for_timeout(1500)


async def _refresh_exports_imports_page(page: Page, log: Callable[[str], None]) -> None:
    log("Wait 5s → refresh Exports/Imports…")
    await page.wait_for_timeout(5000)
    await page.goto(URLS["importExportLogs"], wait_until="domcontentloaded", timeout=180_000)
    await page.wait_for_timeout(2500)
    await _wait_for_grid(page, 60_000)


def _row_locators(page: Page) -> List[Any]:
    return [
        page.locator(".MuiDataGrid-row"),
        page.locator(".MuiDataGrid-virtualScrollerRenderZone > div[data-rowindex]"),
        page.locator('.MuiDataGrid-virtualScrollerRenderZone > div[role="row"]'),
        page.locator('[role="row"][data-id]'),
        page.locator("[role=\"row\"][data-rowindex]"),
        page.locator('[role="grid"] [role="row"]'),
    ]


async def _debug_grid(page: Page, log: Callable[[str], None]) -> None:
    try:
        counts: Dict[str, int] = {}
        for name, sel in [
            ("MuiDataGrid-row", ".MuiDataGrid-row"),
            ("role=row", '[role="row"]'),
            ("data-rowindex", "[data-rowindex]"),
            ("logsResults", '[data-field="logsResults"]'),
        ]:
            counts[name] = await page.locator(sel).count()
        sample = ""
        try:
            sample = await page.locator(
                ".MuiDataGrid-row, [role=\"row\"][data-id], [data-rowindex]"
            ).first.inner_text()
        except Exception:
            pass
        extra = (
            f' · firstRow="{_normalize_status(sample)[:100]}"' if sample else " · no row text"
        )
        log(f"Grid debug: {counts}{extra}")
    except Exception as exc:
        log(f"Grid debug failed: {exc}")


async def _find_latest_export_row(page: Page, log: Callable[[str], None]) -> Any:
    for loc in _row_locators(page):
        try:
            n = await loc.count()
        except Exception:
            n = 0
        if not n:
            continue
        limit = min(n, 15)
        for i in range(limit):
            row = loc.nth(i)
            try:
                text = (await row.inner_text()) or ""
            except Exception:
                text = ""
            if not text.strip():
                continue
            if re.search(r"supplier\s*sku", text, re.I) and re.search(r"status", text, re.I):
                continue
            if _looks_like_export_row(text):
                return row

    type_cell = page.locator(
        '[data-field="logsType"], [data-field="type"], [data-field="jobType"], '
        '[data-field="action"], [data-field="logsAction"]'
    ).filter(has_text=re.compile(r"export", re.I)).first
    if await type_cell.count() > 0:
        row = type_cell.locator(
            'xpath=ancestor::div[contains(@class,"MuiDataGrid-row") or @role="row"][1]'
        )
        if await row.count() > 0:
            return row.first

    await _debug_grid(page, log)
    return None


async def _read_latest_export_row(page: Page, log: Callable[[str], None]) -> Optional[Dict[str, Any]]:
    row = await _find_latest_export_row(page, log)
    if not row:
        return None
    try:
        text = (await row.inner_text()) or ""
    except Exception:
        text = ""
    status_cell = row.locator(
        '[data-field="status"], [data-field="jobStatus"], [data-field="logsStatus"], '
        '[data-field="state"], [data-field="logsStatusDescription"]'
    )
    status_text = ""
    if await status_cell.count():
        try:
            status_text = (await status_cell.first.inner_text()) or ""
        except Exception:
            status_text = ""
    combined = f"{status_text}\n{text}"
    file_match = re.search(r"Cost_Export[^\s]+\.xlsx", text, re.I)
    file_name = file_match.group(0) if file_match else None
    return {
        "row": row,
        "text": text,
        "statusText": status_text or combined,
        "state": _classify_status(combined),
        "fileName": file_name,
        "id": _row_identity(text, file_name),
    }


async def _ensure_results_column_visible(page: Page) -> None:
    """Scroll MUI DataGrid so virtualized Results / actions columns mount."""
    try:
        await page.evaluate(
            """() => {
              const scroller = document.querySelector('.MuiDataGrid-virtualScroller');
              if (!scroller) return;
              scroller.scrollLeft = scroller.scrollWidth;
            }"""
        )
        await page.wait_for_timeout(400)
    except Exception:
        pass


async def _js_find_download_handle(page: Page, file_name: Optional[str] = None) -> Any:
    """DOM search: clickable control only inside the row matching this Cost_Export file."""
    return await page.evaluate_handle(
        """(wantFile) => {
          const want = String(wantFile || '').toUpperCase().trim();
          const isTargetRow = (el) => {
            const t = (el.innerText || '').toUpperCase();
            if (!t.includes('EXPORT')) return false;
            if (!(t.includes('COMPLETED') || t.includes('SUCCESS') || t.includes('COMPLETE'))) {
              return false;
            }
            // Require exact current export filename when known — never another row.
            if (want) return t.includes(want);
            return true;
          };
          const scoreClickable = (el) => {
            if (!el || el.closest('.MuiDataGrid-columnHeaders')) return -1;
            const tag = (el.tagName || '').toLowerCase();
            const text = (el.innerText || el.textContent || '').trim();
            const aria = (el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
            const href = (el.getAttribute('href') || '').toLowerCase();
            const cls = (el.className || '').toString().toLowerCase();
            let score = 0;
            if (/download/i.test(text) || /download/.test(aria) || href.includes('download')) score += 50;
            if (/\\.xlsx/i.test(text) || href.includes('.xlsx') || /cost_export/i.test(text)) score += 40;
            if (el.closest('[data-field="logsResults"], [data-field="results"], [data-field="result"]')) score += 30;
            if (/^\\d{2,}$/.test(text) && el.closest('[data-field="logsResults"], [data-field="results"]')) score += 25;
            if (tag === 'a' || tag === 'button' || el.getAttribute('role') === 'button') score += 10;
            if (cls.includes('iconbutton') || cls.includes('download') || tag === 'svg') score += 8;
            return score;
          };
          const rows = [
            ...document.querySelectorAll('.MuiDataGrid-row'),
            ...document.querySelectorAll('[role="row"][data-id]'),
            ...document.querySelectorAll('[data-rowindex]'),
          ];
          for (const row of rows) {
            if (!isTargetRow(row)) continue;
            let best = null;
            let bestScore = 0;
            const nodes = row.querySelectorAll(
              'a, button, [role="button"], [data-field="logsResults"] *, [data-field="results"] *'
            );
            for (const n of nodes) {
              const s = scoreClickable(n);
              if (s > bestScore) {
                bestScore = s;
                best = n;
              }
            }
            if (!best) {
              const cell = row.querySelector(
                '[data-field="logsResults"], [data-field="results"], [data-field="result"]'
              );
              if (cell) best = cell;
            }
            return best;
          }
          return null;
        }""",
        file_name or "",
    )


async def _click_download_in_row(
    page: Page,
    row: Any,
    log: Callable[[str], None],
    *,
    file_name: Optional[str] = None,
) -> Any:
    """Click download only on the current COMPLETED EXPORT row (one file).

    Never walks other Exports/Imports rows — older Cost_Export files are ignored.
    """
    label = file_name or "current EXPORT row"
    try:
        await row.scroll_into_view_if_needed(timeout=10_000)
    except Exception:
        pass
    await page.wait_for_timeout(500)
    await _ensure_results_column_visible(page)

    results_cell = row.locator(
        '[data-field="logsResults"], [data-field="results"], [data-field="result"], '
        '[role="gridcell"][data-field="logsResults"]'
    )

    # All candidates are scoped to `row` — never page-wide first Download.
    candidates = [
        row.locator(SELECTORS["logsResultsCell"]).get_by_text(re.compile(r"^Download$", re.I)),
        row.get_by_role("link", name=re.compile(r"^Download$", re.I)),
        row.get_by_role("button", name=re.compile(r"^Download$", re.I)),
        row.get_by_text(re.compile(r"^Download$", re.I)),
        results_cell.locator("a, button, [role='button'], .MuiLink-root, .MuiIconButton-root"),
        results_cell.get_by_text(re.compile(r"^\d+$")),
        results_cell,
        row.locator(
            '[data-field="logsResults"] a, [data-field="logsResults"] button, '
            '[data-field="logsResults"] [role="button"], '
            '[data-field="results"] a, [data-field="results"] button, '
            '[data-field="file"] a, [data-field="fileName"] a'
        ),
        row.get_by_role("link", name=re.compile(r"download|cost_export|\.xlsx|^\d+$", re.I)),
        row.locator(
            'a[href*="download" i], a[href*=".xlsx" i], a[download], '
            'button[aria-label*="download" i], [title*="download" i], '
            ".MuiIconButton-root"
        ),
        row.get_by_text(re.compile(r"Cost_Export[^\s]*\.xlsx", re.I)),
        row.locator("a").filter(has_text=re.compile(r"Cost_Export|\.xlsx|download|^\d+$", re.I)),
    ]

    target = None
    for c in candidates:
        try:
            if await c.count() > 0:
                el = c.first
                try:
                    await el.wait_for(state="attached", timeout=2_000)
                except Exception:
                    pass
                target = el
                break
        except Exception:
            continue

    # Fallback still keyed to this export's filename (not "first Download on page").
    if not target and file_name:
        try:
            handle = await _js_find_download_handle(page, file_name)
            el = handle.as_element() if handle else None
            if el:
                target = el
                log(f"Download target resolved via DOM scan for current file only · {file_name}")
        except Exception as exc:
            log(f"DOM download scan failed: {exc}")

    if not target:
        try:
            sample = (await row.inner_text()) or ""
            links = await row.locator("a, button, [role='button']").count()
            results_html = ""
            try:
                if await results_cell.count() > 0:
                    results_html = (await results_cell.first.inner_html())[:300]
            except Exception:
                pass
            log(
                f"Download control not found for current export {label} "
                f"(links/buttons={links}, text={_normalize_status(sample)[:160]}, "
                f"resultsHtml={results_html!r})"
            )
        except Exception as exc:
            log(f"Download control not found (debug failed: {exc})")
        return None

    log(f"Clicking Download on current export only (ignoring older Exports/Imports) · {label}")
    try:
        async with page.expect_download(timeout=300_000) as download_info:
            await target.click(force=True)
        return await download_info.value
    except Exception as exc:
        log(f"Download click did not produce a file: {exc}")
        try:
            async with page.expect_download(timeout=120_000) as download_info:
                await target.click()
            return await download_info.value
        except Exception as exc2:
            log(f"Download retry failed: {exc2}")
            return None


async def wait_and_download_latest_export(
    page: Page,
    log: Optional[Callable[[str], None]] = None,
    *,
    is_cancelled: Optional[Callable[[], bool]] = None,
    max_wait_ms: int = 45 * 60 * 1000,
    downloads_dir: Optional[Path] = None,
) -> str:
    """Poll Exports/Imports until COMPLETED × 3, then download."""
    from automation.browser import (
        CancelledError,
    )

    log_fn = log or logger.info
    same_needed = 3
    dest_dir = Path(downloads_dir) if downloads_dir else DOWNLOADS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    await open_export_import_logs(page, log_fn)

    started_at = time.time() * 1000
    poll = 0
    same_id = None
    same_state = None
    same_count = 0

    while (time.time() * 1000) - started_at < max_wait_ms:
        if callable(is_cancelled) and is_cancelled():
            raise CancelledError("Automation stopped by user")

        await _refresh_exports_imports_page(page, log_fn)
        poll += 1
        elapsed_sec = round(((time.time() * 1000) - started_at) / 1000)

        info = await _read_latest_export_row(page, log_fn)
        if not info:
            same_id = None
            same_state = None
            same_count = 0
            log_fn(f"Check #{poll} ({elapsed_sec}s): no EXPORT row yet — keep waiting")
            continue

        label = info["fileName"] or info["id"]

        if info["state"] == "WAIT":
            same_id = info["id"]
            same_state = "WAIT"
            same_count = 0
            log_fn(f"Check #{poll} ({elapsed_sec}s): IN PROGRESS — wait until COMPLETED · {label}")
            continue

        if info["state"] == "DONE":
            if same_id == info["id"] and same_state == "DONE":
                same_count += 1
            else:
                same_id = info["id"]
                same_state = "DONE"
                same_count = 1

            log_fn(
                f"Check #{poll} ({elapsed_sec}s): COMPLETED same={same_count}/{same_needed} · {label}"
            )

            if same_count >= same_needed:
                log_fn(
                    f"Same COMPLETED export for {same_needed} refreshes (~15s) — "
                    f"downloading current file only (not older exports) · {label}"
                )
                download = await _click_download_in_row(
                    page,
                    info["row"],
                    log_fn,
                    file_name=info.get("fileName"),
                )
                if not download:
                    log_fn("Download control not ready — will refresh again")
                    same_count = max(0, same_count - 1)
                    continue

                suggested = (
                    download.suggested_filename
                    or info["fileName"]
                    or f"Cost_Export_{int(time.time() * 1000)}.xlsx"
                )
                expected = info.get("fileName")
                if (
                    expected
                    and suggested
                    and expected.lower() not in suggested.lower()
                    and suggested.lower() not in expected.lower()
                ):
                    log_fn(
                        f"Skipped unexpected download {suggested!r} "
                        f"(wanted current {expected!r}) — will refresh again"
                    )
                    same_count = max(0, same_count - 1)
                    continue

                target = dest_dir / suggested
                await download.save_as(str(target))
                log_fn(f"Downloaded current export only: {target}")
                return str(target)
            continue

        same_id = info["id"]
        same_state = info["state"]
        same_count = 0
        log_fn(
            f"Check #{poll} ({elapsed_sec}s): status={info['state']} — wait 5s + refresh · {label}"
        )

    raise TimeoutError(
        f"Timed out on Exports/Imports waiting for COMPLETED × {same_needed} "
        f"(last={same_id or 'unknown'})"
    )
