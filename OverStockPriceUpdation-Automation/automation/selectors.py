"""Stable HTML selectors for Overstock Edge Manage Cost / login."""

SELECTORS = {
    "userNameInput": "#userNameInput",
    "passwordInput": "#passwordInput",
    "submitButton": "#submitButton",
    "loginForm": "#loginForm",
    "reviewButton": "#reviewButton",
    "exportButton": "#exportButton",
    "exportSearchResultsBtn": "#exportSearchResultsBtn",
    "exportAllBtn": "#exportAllBtn",
    "importExportButton": "#ImportExportButton",
    "firstCostCell": (
        '[role="gridcell"][data-field="firstCost"], '
        '[role="gridcell"][data-field="FirstCost"], '
        '[role="gridcell"][data-field="currentFirstCost"]'
    ),
    "firstCostHeader": (
        '.MuiDataGrid-columnHeader[data-field="firstCost"], '
        '.MuiDataGrid-columnHeader[aria-label="First Cost"], '
        '[role="columnheader"][aria-label="First Cost"]'
    ),
    "newFirstCostCell": '[role="gridcell"][data-field="newFirstCost"]',
    "logsResultsCell": '[role="gridcell"][data-field="logsResults"]',
    "vendorSkuHeader": (
        '.MuiDataGrid-columnHeader[data-field="vendorSku"], '
        '[role="columnheader"][data-field="vendorSku"]'
    ),
    "importModalJobName": "#ImportModalJobName",
    "importModalUploadButton": "#ImportModalUploadButton",
    "importModalCancelButton": "#ImportModalCancelButton",
    "importModalFileInput": '.modal-content input[type="file"]',
}
