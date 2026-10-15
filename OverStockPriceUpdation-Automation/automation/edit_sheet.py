"""Edit Overstock Cost Export sheet — set New Cost + Cost Increase Reason (openpyxl)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from automation.constants import (
    COST_INCREASE_REASON,
    MANAGE_COST_SHEET,
)
from automation.workbook import load_workbook_tolerant

logger = logging.getLogger(__name__)


def edit_cost_export_sheet(
    input_path: str | Path,
    output_path: str | Path,
    price_by_sku: Mapping[str, float],
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Update New Cost only for Supplier SKUs that are in price_by_sku."""
    log_fn = log or logger.info
    # Overstock Cost_Export often ships invalid stylesheet XML; sanitize like pull/parse.
    wb = load_workbook_tolerant(Path(input_path), read_only=False, data_only=False)
    sheet = None
    if MANAGE_COST_SHEET in wb.sheetnames:
        sheet = wb[MANAGE_COST_SHEET]
    else:
        for name in wb.sheetnames:
            if re.search(r"manage\s*cost", name, re.I):
                sheet = wb[name]
                break
        if sheet is None and wb.sheetnames:
            sheet = wb[wb.sheetnames[-1]]

    if sheet is None:
        raise RuntimeError("Manage Cost sheet not found in export file")

    header_row_number = 3
    sku_col = None
    new_cost_col = None
    reason_col = None

    for cell in sheet[header_row_number]:
        text = str(cell.value or "").strip()
        col = cell.column
        if re.match(r"^supplier\s*sku$", text, re.I):
            sku_col = col
        if re.match(r"^new\s*cost$", text, re.I):
            new_cost_col = col
        if re.search(r"cost\s*increase\s*reason", text, re.I):
            reason_col = col

    if not sku_col or not new_cost_col:
        raise RuntimeError(
            f"Could not find Supplier SKU / New Cost columns "
            f"(skuCol={sku_col}, newCostCol={new_cost_col})"
        )

    updated = 0
    skipped_no_is = 0
    skipped_no_price = 0
    updated_prices: Dict[str, float] = {}

    for row_idx in range(header_row_number + 1, sheet.max_row + 1):
        sku_raw = sheet.cell(row=row_idx, column=sku_col).value
        sku = "" if sku_raw is None else str(sku_raw).strip()
        if not sku:
            continue
        price = price_by_sku.get(sku)
        if price is None:
            skipped_no_price += 1
            continue
        try:
            price_num = float(price)
        except (TypeError, ValueError):
            skipped_no_price += 1
            continue

        sheet.cell(row=row_idx, column=new_cost_col).value = price_num
        if reason_col:
            sheet.cell(row=row_idx, column=reason_col).value = COST_INCREASE_REASON
        updated += 1
        updated_prices[sku] = price_num

    missing = [sku for sku in price_by_sku if sku not in updated_prices]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    log_fn(
        f"Sheet edited: updated={updated}, skippedNoPrice={skipped_no_price}, "
        f"missingFromExport={len(missing)}"
    )
    return {
        "updated": updated,
        "skippedNoIs": skipped_no_is,
        "skippedNoPrice": skipped_no_price,
        "missingCount": len(missing),
        "missingSkus": missing,
        "updatedPrices": updated_prices,
        "outputPath": str(out),
    }
