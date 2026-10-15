"""Overstock Edge URLs and shared automation constants."""

from __future__ import annotations

from automation import settings

URLS = {
    "login": (
        "https://sofslogin.supplieroasis.com/adfs/ls/"
        "?wa=wsignin1.0&wtrealm=urn%3Agateway-ui-edge%3Aprod"
        "&wctx=https%3A%2F%2Fedge.supplieroasis.com%2Fdashboard"
    ),
    "pricing": "https://edge.supplieroasis.com/pricing/?page=1",
    "manageCost": "https://edge.supplieroasis.com/pricing/manage?page=1",
    "importExportLogs": "https://edge.supplieroasis.com/pricing/importExportLogs?page=1",
}

FILTER_PREFIX = getattr(settings, "FILTER_PREFIX", "IS-") or "IS-"
COST_INCREASE_REASON = (
    getattr(settings, "COST_INCREASE_REASON", "Manufacturing Change") or "Manufacturing Change"
)
MANAGE_COST_SHEET = "Manage Cost"
