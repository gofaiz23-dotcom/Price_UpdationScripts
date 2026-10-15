"""Generate or import Overstock prices from input/*.xlsx.

python run.py --one          first SKU only, then import that one price
python run.py --one SKU      that SKU only, then import that one price
python run.py --full         all SKUs in the sheet, then import
python run.py                all SKUs, write the sheet only, do not import
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from automation.method2 import run_method2
from automation.read_input import load_price_sheet
from automation import settings


def _select_prices(prices: dict, mode: str, one_sku: str | None) -> tuple[dict, str, bool]:
    if mode == "one":
        if one_sku:
            key = one_sku.strip()
            if key not in prices:
                raise SystemExit(f"SKU not in the input sheet: {key}")
            chosen = {key: prices[key]}
        else:
            key = next(iter(prices))
            chosen = {key: prices[key]}
        return chosen, key, True
    if mode == "full":
        return prices, settings.FILTER_PREFIX, True
    return prices, settings.FILTER_PREFIX, settings.IMPORT_TO_OVERSTOCK


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--one", nargs="?", const="", metavar="SKU", help="Update one SKU, then import")
    group.add_argument("--full", action="store_true", help="Update every SKU in the input sheet, then import")
    args = parser.parse_args()

    prices = load_price_sheet(settings.INPUT_DIR)
    if args.one is not None:
        mode = "one"
        one_sku = args.one or None
    elif args.full:
        mode = "full"
        one_sku = None
    else:
        mode = "sheet"
        one_sku = None

    chosen, sku_filter, do_import = _select_prices(prices, mode, one_sku)
    print(f"Input SKUs in this run: {len(chosen)}")
    print(f"Filter on Manage Cost: Supplier SKU contains {sku_filter}")
    if do_import:
        print("This run fills the sheet and imports it to Overstock.")
    else:
        print("This run writes the edited sheet to output. It does not import to Overstock.")

    result = asyncio.run(
        run_method2(
            price_by_sku=chosen,
            headless=settings.AUTOMATION_HEADLESS,
            filter=sku_filter,
            import_sheet=do_import,
        )
    )
    print(f"Updated rows: {result.get('updated')}")
    print(f"SKUs in the input sheet not found on the export: {result.get('missingCount')}")
    print(f"Edited sheet: {result.get('editedPath')}")
    if result.get("missingSkus"):
        print("Missing SKUs:")
        for sku in result["missingSkus"]:
            print(f"  {sku}")
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
