from __future__ import annotations

from collections import defaultdict

from rv_dashboard.configure import build_configuration, write_profile
from rv_dashboard.envfile import encode_env_value, parse_env_file, update_env_file
from rv_dashboard.operator_auth import verify_operator_pin
from rv_dashboard.profile import load_profile


class ScriptedPrompter:
    def __init__(self, *, text=None, yes_no=None, choices=None, integers=None, secret=None):
        self.text_values = defaultdict(list, text or {})
        self.yes_no_values = defaultdict(list, yes_no or {})
        self.choice_values = defaultdict(list, choices or {})
        self.integer_values = defaultdict(list, integers or {})
        self.secret_values = defaultdict(list, secret or {})
        self.messages: list[str] = []

    @staticmethod
    def _next(values, label, default):
        configured = values[label]
        return configured.pop(0) if configured else default

    def output(self, message):
        self.messages.append(message)

    def text(self, label, default="", **_kwargs):
        return self._next(self.text_values, label, default)

    def yes_no(self, label, default):
        return self._next(self.yes_no_values, label, default)

    def choice(self, label, _choices, default):
        return self._next(self.choice_values, label, default)

    def integer(self, label, default, **_kwargs):
        return self._next(self.integer_values, label, default)

    def secret(self, label, *, has_existing):
        return self._next(self.secret_values, label, None if has_existing else None)


def test_environment_values_round_trip_and_comments_are_preserved(tmp_path):
    env_file = tmp_path / "dashboard.env"
    env_file.write_text("# keep this comment\nDASHBOARD_MODE=demo\nRVW_PASSWORD=old\n", encoding="utf-8")
    password = "space and 'quote\""

    update_env_file(env_file, {"DASHBOARD_MODE": "live", "RVW_PASSWORD": password, "RVW_ID": "sample"})

    content = env_file.read_text(encoding="utf-8")
    assert content.startswith("# keep this comment\n")
    assert parse_env_file(env_file) == {
        "DASHBOARD_MODE": "live",
        "RVW_PASSWORD": password,
        "RVW_ID": "sample",
    }
    assert encode_env_value("plain-value") == "plain-value"


def test_wizard_configures_local_access_sections_and_variable_climate_items():
    profile = load_profile(None)
    environment = {
        "DASHBOARD_MODE": "demo",
        "RVW_ACCESS_MODE": "gateway",
        "RVW_USERNAME": "old-user",
        "RVW_PASSWORD": "old-password",
    }
    prompts = ScriptedPrompter(
        text={
            "RV display name": ["Road Home"],
            "Short monogram": ["RH"],
            "RV Whisper base URL": ["http://rvm.local"],
            "Display label": ["Pet zone", "Refrigerator"],
            "Normalized metric path": [
                "environment.pet_zone.temperature",
                "environment.refrigerator.temperature",
            ],
        },
        yes_no={
            "Enable live mode now?": [True],
            "Enable House Battery?": [False],
            "Enable Climate?": [True],
            "Change the climate item list?": [True],
            "Show on Home?": [True, True],
            "Enable Tanks?": [False],
        },
        choices={"Connection type": ["local"]},
        integers={"Number of climate items": [2]},
    )

    updated, env_updates = build_configuration(profile, environment, prompts)

    assert updated["vehicle"]["name"] == "Road Home"
    assert updated["vehicle"]["monogram"] == "RH"
    assert updated["sections"]["battery"]["enabled"] is False
    assert updated["sections"]["tanks"]["enabled"] is False
    assert [item["path"] for item in updated["sections"]["climate"]["items"]] == [
        "environment.pet_zone.temperature",
        "environment.refrigerator.temperature",
    ]
    assert env_updates == {
        "RVW_ACCESS_MODE": "local",
        "RVW_BASE_URL": "http://rvm.local",
        "RVW_ID": "",
        "RVW_SYSTEM_PATH": "",
        "RVW_USERNAME": "",
        "RVW_PASSWORD": "",
        "RVW_LOCAL_USERNAME": "",
        "RVW_LOCAL_PASSWORD": "",
        "ALLOW_ALERT_ACK": "false",
        "DASHBOARD_MODE": "live",
    }


def test_wizard_keeps_device_local_credentials_separate_from_gateway_credentials():
    prompts = ScriptedPrompter(
        choices={"Connection type": ["local"]},
        text={
            "RV Whisper base URL": ["http://rvm.local"],
            "RVM3 local username": ["device-user"],
        },
        yes_no={
            "Use device-local credentials for acknowledged alert status?": [True],
            "Enable live mode now?": [True],
        },
        secret={"RVM3 local password": ["device-password"]},
    )

    _profile, updates = build_configuration(
        load_profile(None),
        {
            "DASHBOARD_MODE": "demo",
            "RVW_USERNAME": "cloud-user",
            "RVW_PASSWORD": "cloud-password",
        },
        prompts,
    )

    assert updates["RVW_USERNAME"] == ""
    assert updates["RVW_PASSWORD"] == ""
    assert updates["RVW_LOCAL_USERNAME"] == "device-user"
    assert updates["RVW_LOCAL_PASSWORD"] == "device-password"
    assert updates["DASHBOARD_MODE"] == "live"


def test_wizard_hashes_operator_pin_when_acknowledgement_is_enabled():
    prompts = ScriptedPrompter(
        choices={"Connection type": ["local"]},
        text={
            "RV Whisper base URL": ["http://rvm.local"],
            "RVM3 local username": ["device-user"],
        },
        yes_no={
            "Use device-local credentials for acknowledged alert status?": [True],
            "Enable dashboard alert acknowledgement?": [True],
            "Enable live mode now?": [True],
        },
        secret={
            "RVM3 local password": ["device-password"],
            "Dashboard operator PIN (4-12 digits)": ["4826"],
            "Confirm dashboard operator PIN": ["4826"],
        },
    )

    _profile, updates = build_configuration(load_profile(None), {"DASHBOARD_MODE": "demo"}, prompts)

    assert updates["ALLOW_ALERT_ACK"] == "true"
    assert "4826" not in updates["DASHBOARD_OPERATOR_PIN_HASH"]
    assert verify_operator_pin("4826", updates["DASHBOARD_OPERATOR_PIN_HASH"]) is True


def test_incomplete_gateway_credentials_keep_demo_mode():
    prompts = ScriptedPrompter(
        choices={"Connection type": ["gateway"]},
        text={
            "RV Whisper base URL": ["https://access.rvwhisper.com"],
            "RVM identifier": ["sample-rvm"],
            "Gateway username": [""],
        },
        yes_no={"Enable live mode now?": [True]},
    )

    _profile, updates = build_configuration(load_profile(None), {"DASHBOARD_MODE": "demo"}, prompts)

    assert updates["DASHBOARD_MODE"] == "demo"
    assert any("credentials are incomplete" in message for message in prompts.messages)


def test_profile_write_is_valid_and_complete(tmp_path):
    path = tmp_path / "dashboard-profile.json"
    profile = load_profile(None)
    profile["vehicle"]["name"] = "Test Rig"

    write_profile(path, profile)

    assert load_profile(path)["vehicle"]["name"] == "Test Rig"
    assert not list(tmp_path.glob(".dashboard-profile.json-*"))
