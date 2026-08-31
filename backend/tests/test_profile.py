import json

import pytest

from rv_dashboard.profile import load_profile, validate_profile


def test_profile_supports_variable_climate_and_tank_counts(tmp_path):
    raw = {
        "schema_version": 1,
        "vehicle": {"name": "Road Home", "subtitle": "Systems", "monogram": "RH"},
        "sections": {
            "battery": {"enabled": True, "label": "Battery"},
            "ac_power": {"enabled": False, "label": "AC Power"},
            "climate": {
                "enabled": True,
                "label": "Temperatures",
                "items": [
                    {"id": "pet-zone", "label": "Pet zone", "path": "environment.pet.temperature", "home": True},
                ],
            },
            "tanks": {"enabled": True, "label": "Levels", "items": []},
            "events": {"enabled": True, "label": "Alerts"},
        },
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    profile = load_profile(path)

    assert profile["vehicle"]["name"] == "Road Home"
    assert profile["sections"]["ac_power"]["enabled"] is False
    assert len(profile["sections"]["climate"]["items"]) == 1
    assert profile["sections"]["tanks"]["items"] == []


def test_profile_rejects_invalid_metric_path():
    raw = load_profile(None)
    raw["sections"]["climate"]["items"][0]["path"] = "../../secret"

    with pytest.raises(ValueError, match="normalized path"):
        validate_profile(raw)


def test_missing_profile_uses_safe_default(tmp_path):
    profile = load_profile(tmp_path / "missing.json")
    assert profile["schema_version"] == 1
    assert profile["vehicle"]["name"]
