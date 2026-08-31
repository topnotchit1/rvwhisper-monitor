from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


PATH_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,120}$")
TANK_TONES = {"fresh", "gray", "black", "propane"}

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": 1,
    "vehicle": {
        "name": "Minnie Winnie",
        "subtitle": "Unified systems",
        "monogram": "MW",
    },
    "sections": {
        "battery": {"enabled": True, "label": "House Battery"},
        "ac_power": {"enabled": True, "label": "AC Power"},
        "climate": {
            "enabled": True,
            "label": "Climate",
            "items": [
                {"id": "front-room", "label": "Front room", "path": "environment.front_room.temperature", "home": True},
                {"id": "bedroom", "label": "Bedroom", "path": "environment.bedroom.temperature", "home": True},
                {"id": "refrigerator", "label": "Refrigerator", "path": "environment.fridge.temperature", "home": True},
                {"id": "freezer", "label": "Freezer", "path": "environment.freezer.temperature", "home": True},
            ],
        },
        "tanks": {
            "enabled": True,
            "label": "Tanks",
            "items": [
                {"id": "fresh", "label": "Fresh", "path": "tank.fresh.percent", "tone": "fresh", "home": True},
                {"id": "gray", "label": "Gray", "path": "tank.gray.percent", "tone": "gray", "home": True},
                {"id": "black", "label": "Black", "path": "tank.black.percent", "tone": "black", "home": True},
                {"id": "propane", "label": "Propane", "path": "tank.propane.percent", "tone": "propane", "home": True},
            ],
        },
        "events": {"enabled": True, "label": "Events"},
    },
}


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{label} must be a non-empty string no longer than {maximum} characters")
    return value.strip()


def _section(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return {
        "enabled": bool(value.get("enabled", True)),
        "label": _text(value.get("label"), f"{label}.label", 40),
    }


def _items(value: object, label: str, *, tanks: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 24:
        raise ValueError(f"{label} must be a list containing no more than 24 items")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        item_id = _text(raw.get("id"), f"{label}[{index}].id", 50)
        if item_id in seen:
            raise ValueError(f"{label} contains duplicate id {item_id}")
        seen.add(item_id)
        path = _text(raw.get("path"), f"{label}[{index}].path", 120)
        if not PATH_PATTERN.fullmatch(path):
            raise ValueError(f"{label}[{index}].path is not a valid normalized path")
        item = {
            "id": item_id,
            "label": _text(raw.get("label"), f"{label}[{index}].label", 40),
            "path": path,
            "home": bool(raw.get("home", True)),
        }
        if tanks:
            tone = str(raw.get("tone", "gray"))
            if tone not in TANK_TONES:
                raise ValueError(f"{label}[{index}].tone must be one of {sorted(TANK_TONES)}")
            item["tone"] = tone
        result.append(item)
    return result


def validate_profile(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Dashboard profile schema_version must be 1")
    vehicle = raw.get("vehicle")
    sections = raw.get("sections")
    if not isinstance(vehicle, dict) or not isinstance(sections, dict):
        raise ValueError("Dashboard profile requires vehicle and sections objects")
    profile = {
        "schema_version": 1,
        "vehicle": {
            "name": _text(vehicle.get("name"), "vehicle.name", 60),
            "subtitle": _text(vehicle.get("subtitle"), "vehicle.subtitle", 80),
            "monogram": _text(vehicle.get("monogram"), "vehicle.monogram", 4).upper(),
        },
        "sections": {
            "battery": _section(sections.get("battery"), "sections.battery"),
            "ac_power": _section(sections.get("ac_power"), "sections.ac_power"),
            "events": _section(sections.get("events"), "sections.events"),
        },
    }
    climate = _section(sections.get("climate"), "sections.climate")
    climate["items"] = _items(sections["climate"].get("items"), "sections.climate.items")
    if any(not item["path"].endswith(".temperature") for item in climate["items"]):
        raise ValueError("Climate item paths must end with .temperature")
    tanks = _section(sections.get("tanks"), "sections.tanks")
    tanks["items"] = _items(sections["tanks"].get("items"), "sections.tanks.items", tanks=True)
    profile["sections"]["climate"] = climate
    profile["sections"]["tanks"] = tanks
    return profile


def load_profile(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return copy.deepcopy(DEFAULT_PROFILE)
    profile_path = Path(path)
    if not profile_path.exists():
        return copy.deepcopy(DEFAULT_PROFILE)
    return validate_profile(json.loads(profile_path.read_text(encoding="utf-8")))
