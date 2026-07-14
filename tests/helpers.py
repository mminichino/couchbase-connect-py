"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

RESOURCES = Path(__file__).resolve().parent / "resources"


def load_properties(resource_name: str) -> Dict[str, str]:
    path = RESOURCES / resource_name
    if not path.is_file():
        raise FileNotFoundError(path)
    properties: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def capella_properties_available(resource_name: str) -> bool:
    path = RESOURCES / resource_name
    if not path.is_file():
        return False
    props = load_properties(resource_name)
    token = props.get("capella.token", "")
    if not token:
        return False
    # Example files ship placeholders (YOUR_CAPELLA_*, TOKEN, etc.).
    upper = token.upper()
    if "YOUR_CAPELLA" in upper or upper in {"TOKEN", "CHANGE_ME", "REPLACE_ME"}:
        return False
    return True
