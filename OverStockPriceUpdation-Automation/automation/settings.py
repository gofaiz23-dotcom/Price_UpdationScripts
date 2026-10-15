"""Local settings for the HNF Overstock price-sheet automation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"

# Manage Cost "Supplier SKU Contains" filter. HNF SKUs end with -HNF.
FILTER_PREFIX = "-HNF"
COST_INCREASE_REASON = "Manufacturing Change"

# False = visible Chromium window. True = no window.
AUTOMATION_HEADLESS = False
AUTOMATION_SLOW_MO_MS = 100

ENV_USERNAME = "OVERSTOCK_USERNAME"
ENV_PASSWORD = "OVERSTOCK_PASSWORD"
EDGE_LOGIN_DOMAIN = "supplieroasis.com"

# Sheet is written to output/. Import to Overstock stays off.
IMPORT_TO_OVERSTOCK = False
