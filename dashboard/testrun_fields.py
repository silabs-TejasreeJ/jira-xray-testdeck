"""Test Run custom fields shown under Xray Test Details."""

from __future__ import annotations

from typing import Any

# Exact labels from Xray "Test Details → Custom Fields"
TEST_RUN_CUSTOM_FIELDS: list[dict[str, str]] = [
    {"key": "feature_name", "label": "feature_name"},
    {"key": "sub_feature_name", "label": "sub_feature_name"},
    {"key": "jenkins_test_results_url", "label": "jenkins_test_results_url"},
    {"key": "evk_version", "label": "EVK Version"},
    {"key": "host_platform", "label": "Host Platform"},
    {"key": "build_version", "label": "Build Version"},
    {"key": "interface_type", "label": "Interface type"},
    {"key": "test_mode", "label": "Test Mode"},
    {"key": "test_execution_method", "label": "Test_Execution_Method"},
    {"key": "board_details", "label": "Board_Details"},
    {"key": "measured_kpi_value", "label": "Measured KPI value"},
    {"key": "target_kpi_value", "label": "Target KPI Value"},
]

# Seed options from Xray Test Details dropdowns (Silabs).
SEED_OPTIONS: dict[str, list[str]] = {
    "feature_name": [],
    "sub_feature_name": [],
    "jenkins_test_results_url": [],
    "evk_version": [
        "SI917 B0 2.0 RADIO BOARD",
        "Si917 B0 2.0 RADIO BOARD",
        "9116 1.5 ACX",
        "9117 EVK",
        "FPGA_13p",
        "CCP_Radio_Board",
        "9117 EXP_Board",
        "EVK 1.4",
        "EVK 1.5",
        "EVK 1.3",
        "B00 1.4",
    ],
    "host_platform": [
        "WAND Board",
        "X86",
        "EFM",
        "RT595/SDIO",
        "K28/FRDM",
        "STM32",
        "EFR",
        "Garmin/EVB",
        "NCP",
        "SoC",
        "SOC",
    ],
    "build_version": [
        "wifi_sdk-4.1.1-CF(SiWG917-B.2.16.5.1.0.6)",
        "wifi_sdk-4.1.1-CF(SIWG917-B.2.16.5.1.0.6)",
    ],
    "interface_type": [
        "SPI",
        "SDIO",
        "USB",
        "USB-CDC",
        "UART",
        "SOC",
        "NCP",
        "SoC",
    ],
    "test_mode": ["WIFISDK 3.0", "WIFISDK 2.0"],
    "test_execution_method": [
        "Automation first run",
        "Automation rerun",
        "Manual",
    ],
    "board_details": [],
    "measured_kpi_value": [],
    "target_kpi_value": [],
}


def normalize_field_label(name: str) -> str:
    return " ".join((name or "").strip().lower().replace("_", " ").replace("-", " ").split())


LABEL_TO_KEY: dict[str, str] = {
    normalize_field_label(item["label"]): item["key"] for item in TEST_RUN_CUSTOM_FIELDS
}
# Extra aliases seen in Network / Xray UI
LABEL_TO_KEY.update(
    {
        normalize_field_label("TESTMODE"): "test_mode",
        normalize_field_label("TestMode"): "test_mode",
        normalize_field_label("INTERFACE TYPE"): "interface_type",
        normalize_field_label("Interface Type"): "interface_type",
    }
)

# Bump catalog cache when confirmed IDs change (see settings.XRAY_TRCF_IDS).


def match_field_key(name: str) -> str:
    norm = normalize_field_label(name)
    if not norm:
        return ""
    if norm in LABEL_TO_KEY:
        return LABEL_TO_KEY[norm]
    # Fuzzy: API names sometimes include extra words / different punctuation.
    for label_norm, key in LABEL_TO_KEY.items():
        if label_norm == norm:
            return key
        if label_norm in norm or norm in label_norm:
            return key
        # compact compare: "evkversion" == "evk version"
        if label_norm.replace(" ", "") == norm.replace(" ", ""):
            return key
    return ""


def empty_field_catalog() -> list[dict[str, Any]]:
    catalog = []
    for item in TEST_RUN_CUSTOM_FIELDS:
        catalog.append(
            {
                "key": item["key"],
                "label": item["label"],
                "id": None,
                "options": list(SEED_OPTIONS.get(item["key"]) or []),
                "current": "",
            }
        )
    return catalog


def is_valid_trcf_id(field_id: Any) -> bool:
    """Xray Test Run custom field IDs are positive integers."""
    try:
        return int(field_id) > 0
    except (TypeError, ValueError):
        return False


def normalize_trcf_value(value: Any) -> str:
    """Coerce a TRCF value to a clean display/option string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        text = (
            value.get("rendered")
            or value.get("value")
            or value.get("name")
            or value.get("label")
            or value.get("raw")
            or ""
        )
        # Skip empty Jira dual-value shells: {"raw":"","rendered":""}
        if isinstance(text, dict):
            return normalize_trcf_value(text)
        return str(text or "").strip()
    text = str(value).strip()
    if not text or text in {"{}", "None", "null"}:
        return ""
    # Reject accidental dict/json dumps used as option labels.
    if text.startswith("{") and ("raw" in text or "rendered" in text):
        return ""
    return text


def extract_named_ids(node: Any, found: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Recursively find objects that look like {id, name} custom-field defs."""
    if found is None:
        found = []
    if isinstance(node, dict):
        name = node.get("name") or node.get("label") or node.get("customFieldName")
        # Prefer explicit customFieldId — bare "id" is often an unrelated nested object.
        field_id = node.get("customFieldId") or node.get("cfId")
        if field_id is None and name and is_valid_trcf_id(node.get("id")):
            field_id = node.get("id")
        if name and is_valid_trcf_id(field_id):
            found.append(
                {
                    "name": str(name).strip(),
                    "id": field_id,
                    "options": node.get("options")
                    or node.get("allowedValues")
                    or node.get("values")
                    or [],
                    "value": node.get("value"),
                }
            )
        for value in node.values():
            extract_named_ids(value, found)
    elif isinstance(node, list):
        for item in node:
            extract_named_ids(item, found)
    return found
