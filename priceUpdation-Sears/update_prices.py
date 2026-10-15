"""Push Proposed Price from sears-HNF-matched.xlsx to Sears in bulk."""

from __future__ import annotations

import hashlib
import hmac
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent
SHEET = ROOT.parent / "sears-HNF-matched.xlsx"
ENV_PATH = ROOT / ".env"
RESULTS = ROOT / "results"
BATCH_SIZE = 5000
TIMEOUT_SECONDS = 180

NS = "http://seller.marketplace.sears.com/pricing/v6"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA = "http://seller.marketplace.sears.com/pricing/v6 ../../../../../rest/pricing/import/v6/pricing.xsd"


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Missing {path}. Fill SEARS_SELLER_ID, SEARS_EMAIL, SEARS_SECRET_KEY_BASE64, SEARS_BASE_URL.")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def require(env: dict[str, str], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise SystemExit(f"{key} is empty in {ENV_PATH}")
    return value


def load_rows(sheet: Path) -> list[tuple[str, str]]:
    frame = pd.read_excel(sheet)
    if "SKU" not in frame.columns or "Proposed Price" not in frame.columns:
        raise SystemExit(f"{sheet} needs columns SKU and Proposed Price. Found {list(frame.columns)}")
    by_sku: dict[str, str] = {}
    skipped = 0
    replaced = 0
    for sku, price in zip(frame["SKU"], frame["Proposed Price"]):
        item_id = str(sku).strip()
        if not item_id or item_id.lower() == "nan":
            skipped += 1
            continue
        if pd.isna(price):
            skipped += 1
            continue
        amount = float(price)
        if amount <= 0:
            skipped += 1
            continue
        text = f"{amount:.2f}"
        if item_id in by_sku and by_sku[item_id] != text:
            replaced += 1
        by_sku[item_id] = text
    if skipped:
        print(f"Skipped {skipped} rows with a blank SKU or price.")
    if replaced:
        print(f"{replaced} duplicate SKUs had more than one price. The last price in the sheet is used.")
    if not by_sku:
        raise SystemExit("No prices to send.")
    return list(by_sku.items())


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_feed(items: list[tuple[str, str]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        f'<pricing-feed xmlns="{NS}" xmlns:xsi="{XSI}" xsi:schemaLocation="{SCHEMA}">'
    )
    lines.append("    <fbm-pricing>")
    for item_id, price in items:
        lines.append(f'        <item item-id="{escape_xml(item_id)}">')
        lines.append(f"            <standard-price>{escape_xml(price)}</standard-price>")
        lines.append("        </item>")
    lines.append("    </fbm-pricing>")
    lines.append("</pricing-feed>")
    return "\n".join(lines)


def authorization_header(seller_id: str, email: str, secret: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signed = f"{seller_id}:{email}:{timestamp}"
    signature = hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"HMAC-SHA256 emailaddress={email},timestamp={timestamp},signature={signature}"


def put_feed(url: str, body: str, header: str) -> tuple[int, str]:
    request = Request(
        url,
        data=body.encode("utf-8"),
        method="PUT",
        headers={
            "Content-Type": "application/xml",
            "Accept": "application/xml",
            "Authorization": header,
            "User-Agent": "axios/1.6.8",
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


def document_id(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag in {"document-id", "documentId"} and (element.text or "").strip():
            return element.text.strip()
    return ""


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    env = load_env(ENV_PATH)
    seller_id = require(env, "SEARS_SELLER_ID")
    email = require(env, "SEARS_EMAIL")
    secret = require(env, "SEARS_SECRET_KEY_BASE64")
    base = require(env, "SEARS_BASE_URL").rstrip("/")
    items = load_rows(SHEET)
    print(f"SKUs to update: {len(items)}")
    url = f"{base}/SellerPortal/api/pricing/fbm/v6?{urlencode({'sellerId': seller_id})}"
    RESULTS.mkdir(exist_ok=True)
    failures = 0
    for index, start in enumerate(range(0, len(items), BATCH_SIZE), start=1):
        chunk = items[start : start + BATCH_SIZE]
        body = build_feed(chunk)
        feed_path = RESULTS / f"batch-{index}-request.xml"
        feed_path.write_text(body, encoding="utf-8")
        print(f"Batch {index}: {len(chunk)} items")
        if dry_run:
            print(f"Dry run. XML saved to {feed_path}")
            continue
        status, response_text = put_feed(url, body, authorization_header(seller_id, email, secret))
        response_path = RESULTS / f"batch-{index}-response.xml"
        response_path.write_text(response_text, encoding="utf-8")
        doc = document_id(response_text)
        print(f"Sears status {status}. document-id: {doc or 'not returned'}")
        print(f"Response saved to {response_path}")
        if status >= 400:
            failures += 1
            print(response_text[:500])
    if failures:
        raise SystemExit(f"{failures} batch(es) failed.")
    if not dry_run:
        print("Price update sent.")


if __name__ == "__main__":
    try:
        main()
    except URLError as exc:
        raise SystemExit(f"Could not reach Sears: {exc}") from exc
