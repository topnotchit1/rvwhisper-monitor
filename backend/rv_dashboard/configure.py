from __future__ import annotations

import argparse
import copy
import getpass
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .envfile import parse_env_file, update_env_file
from .profile import TANK_TONES, load_profile, validate_profile


IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]*$")
SYSTEM_PATH = re.compile(r"^/?[A-Za-z0-9._/-]*$")


class Prompter:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        secret_fn: Callable[[str], str] = getpass.getpass,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self.input = input_fn
        self.secret_input = secret_fn
        self.output = output_fn

    def text(
        self,
        label: str,
        default: str = "",
        *,
        maximum: int = 120,
        optional: bool = False,
        validator: Callable[[str], str] | None = None,
    ) -> str:
        suffix = f" [{default}]" if default else (" [optional]" if optional else "")
        while True:
            value = self.input(f"{label}{suffix}: ").strip()
            value = value or default
            if not value and not optional:
                self.output(f"{label} is required.")
                continue
            if len(value) > maximum:
                self.output(f"{label} must contain no more than {maximum} characters.")
                continue
            try:
                return validator(value) if validator else value
            except ValueError as exc:
                self.output(str(exc))

    def yes_no(self, label: str, default: bool) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            value = self.input(f"{label} [{suffix}] ").strip().casefold()
            if not value:
                return default
            if value in {"y", "yes"}:
                return True
            if value in {"n", "no"}:
                return False
            self.output("Enter yes or no.")

    def choice(self, label: str, choices: dict[str, str], default: str) -> str:
        keys = "/".join(choices)
        while True:
            value = self.input(f"{label} ({keys}) [{default}]: ").strip().casefold() or default
            if value in choices:
                return choices[value]
            self.output(f"Choose one of: {', '.join(choices)}.")

    def integer(self, label: str, default: int, *, minimum: int = 0, maximum: int = 24) -> int:
        while True:
            value = self.input(f"{label} [{default}]: ").strip()
            try:
                result = default if not value else int(value)
            except ValueError:
                self.output("Enter a whole number.")
                continue
            if minimum <= result <= maximum:
                return result
            self.output(f"Enter a number from {minimum} through {maximum}.")

    def secret(self, label: str, *, has_existing: bool) -> str | None:
        suffix = " [leave blank to keep existing]" if has_existing else " [optional]"
        value = self.secret_input(f"{label}{suffix}: ")
        if not value:
            return None
        if any(character in value for character in "\r\n\x00"):
            raise ValueError("Passwords cannot contain line breaks or NUL bytes")
        return value


def _validated_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a complete http:// or https:// address.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Enter only the device origin; put any dashboard path in the next field.")
    if parsed.username or parsed.password:
        raise ValueError("Do not place credentials in the URL.")
    return value.rstrip("/")


def _validated_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("The identifier may contain only letters, numbers, dots, underscores, and hyphens.")
    return value


def _validated_system_path(value: str) -> str:
    if not SYSTEM_PATH.fullmatch(value):
        raise ValueError("The dashboard path contains unsupported characters.")
    if not value:
        return ""
    return "/" + value.strip("/")


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result[:50] or "sensor"


def _metric_segment(value: str) -> str:
    return _slug(value).replace("-", "_")


def _configure_items(
    prompts: Prompter,
    current: list[dict[str, Any]],
    *,
    label: str,
    tanks: bool,
) -> list[dict[str, Any]]:
    if not prompts.yes_no(f"Change the {label.casefold()} item list?", False):
        return copy.deepcopy(current)
    count = prompts.integer(f"Number of {label.casefold()} items", len(current))
    items: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    home_count = 0
    for index in range(count):
        previous = current[index] if index < len(current) else {}
        prompts.output(f"\n{label} item {index + 1} of {count}")
        item_label = prompts.text("Display label", str(previous.get("label", "")), maximum=40)
        default_id = str(previous.get("id") or _slug(item_label))
        item_id = prompts.text("Stable item ID", default_id, maximum=50)
        while item_id in used_ids:
            prompts.output("That item ID is already used in this section.")
            item_id = prompts.text("Stable item ID", f"{default_id}-{index + 1}", maximum=50)
        used_ids.add(item_id)
        default_path = str(previous.get("path") or (
            f"tank.{_metric_segment(item_label)}.percent"
            if tanks
            else f"environment.{_metric_segment(item_label)}.temperature"
        ))
        path = prompts.text("Normalized metric path", default_path, maximum=120)
        default_home = bool(previous.get("home", index < 4)) and home_count < 4
        home = prompts.yes_no("Show on Home?", default_home) if home_count < 4 else False
        if home:
            home_count += 1
        item: dict[str, Any] = {"id": item_id, "label": item_label, "path": path, "home": home}
        if tanks:
            default_tone = str(previous.get("tone", "gray"))
            item["tone"] = prompts.choice(
                "Gauge color",
                {tone: tone for tone in sorted(TANK_TONES)},
                default_tone if default_tone in TANK_TONES else "gray",
            )
        items.append(item)
    return items


def build_configuration(
    profile: dict[str, Any],
    environment: dict[str, str],
    prompts: Prompter,
) -> tuple[dict[str, Any], dict[str, str]]:
    updated = copy.deepcopy(profile)
    vehicle = updated["vehicle"]
    prompts.output("\nRV identity")
    vehicle["name"] = prompts.text("RV display name", vehicle["name"], maximum=60)
    vehicle["subtitle"] = prompts.text("Subtitle", vehicle["subtitle"], maximum=80)
    vehicle["monogram"] = prompts.text("Short monogram", vehicle["monogram"], maximum=4).upper()

    prompts.output("\nRV Whisper connection")
    current_mode = environment.get("DASHBOARD_MODE", "demo").casefold()
    current_access = environment.get("RVW_ACCESS_MODE", "local").casefold()
    default_connection = "demo" if current_mode != "live" else current_access
    if default_connection not in {"demo", "local", "gateway"}:
        default_connection = "demo"
    connection = prompts.choice(
        "Connection type",
        {"demo": "demo", "local": "local", "gateway": "gateway"},
        default_connection,
    )
    env_updates: dict[str, str] = {}
    if connection == "demo":
        env_updates["DASHBOARD_MODE"] = "demo"
    else:
        env_updates["RVW_ACCESS_MODE"] = connection
        default_url = environment.get("RVW_BASE_URL", "")
        if not default_url:
            default_url = "https://access.rvwhisper.com" if connection == "gateway" else ""
        env_updates["RVW_BASE_URL"] = prompts.text(
            "RV Whisper base URL",
            default_url,
            maximum=200,
            validator=_validated_url,
        )
        env_updates["RVW_ID"] = prompts.text(
            "RVM identifier",
            environment.get("RVW_ID", ""),
            maximum=80,
            optional=connection == "local",
            validator=_validated_identifier,
        )
        env_updates["RVW_SYSTEM_PATH"] = prompts.text(
            "Dashboard path (blank means root)",
            environment.get("RVW_SYSTEM_PATH", ""),
            maximum=120,
            optional=True,
            validator=_validated_system_path,
        )
        if connection == "local":
            env_updates["RVW_USERNAME"] = ""
            env_updates["RVW_PASSWORD"] = ""
        else:
            username = prompts.text(
                "Gateway username",
                environment.get("RVW_USERNAME", ""),
                maximum=160,
                optional=True,
            )
            env_updates["RVW_USERNAME"] = username
            password = prompts.secret("Gateway password", has_existing=bool(environment.get("RVW_PASSWORD")))
            if password is not None:
                env_updates["RVW_PASSWORD"] = password
        can_go_live = connection == "local" or bool(
            env_updates.get("RVW_USERNAME") and (env_updates.get("RVW_PASSWORD") or environment.get("RVW_PASSWORD"))
        )
        enable_live = prompts.yes_no("Enable live mode now?", current_mode == "live")
        if enable_live and not can_go_live:
            prompts.output("Gateway credentials are incomplete; keeping the dashboard in demo mode.")
        env_updates["DASHBOARD_MODE"] = "live" if enable_live and can_go_live else "demo"

    prompts.output("\nDashboard sections")
    sections = updated["sections"]
    for key in ("battery", "ac_power"):
        section = sections[key]
        section["enabled"] = prompts.yes_no(f"Enable {section['label']}?", section["enabled"])
        section["label"] = prompts.text(f"{key.replace('_', ' ').title()} label", section["label"], maximum=40)
    climate = sections["climate"]
    climate["enabled"] = prompts.yes_no(f"Enable {climate['label']}?", climate["enabled"])
    climate["label"] = prompts.text("Climate section label", climate["label"], maximum=40)
    if climate["enabled"]:
        climate["items"] = _configure_items(prompts, climate["items"], label="Climate", tanks=False)
    tanks = sections["tanks"]
    tanks["enabled"] = prompts.yes_no(f"Enable {tanks['label']}?", tanks["enabled"])
    tanks["label"] = prompts.text("Tanks section label", tanks["label"], maximum=40)
    if tanks["enabled"]:
        tanks["items"] = _configure_items(prompts, tanks["items"], label="Tank", tanks=True)
    events = sections["events"]
    events["enabled"] = prompts.yes_no(f"Enable {events['label']}?", events["enabled"])
    events["label"] = prompts.text("Events section label", events["label"], maximum=40)
    return validate_profile(updated), env_updates


def write_profile(path: str | Path, profile: dict[str, Any], *, mode: int = 0o640) -> None:
    profile_path = Path(path)
    validated = validate_profile(profile)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{profile_path.name}-", dir=profile_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(validated, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, profile_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _summary(profile: dict[str, Any], environment: dict[str, str]) -> list[str]:
    sections = profile["sections"]
    enabled = [section["label"] for section in sections.values() if section["enabled"]]
    return [
        f"RV: {profile['vehicle']['name']} ({profile['vehicle']['monogram']})",
        f"Mode: {environment.get('DASHBOARD_MODE', 'demo')}",
        f"RV Whisper access: {environment.get('RVW_ACCESS_MODE', 'local')}",
        f"Enabled sections: {', '.join(enabled) or 'none'}",
        f"Climate items: {len(sections['climate']['items'])}",
        f"Tank items: {len(sections['tanks']['items'])}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configure an RV dashboard installation without editing JSON by hand.")
    parser.add_argument("--config-dir", type=Path, default=Path(os.getenv("CONFIG_DIR", "/etc/minnie-dashboard")))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate and summarize the current configuration without changing it.")
    args = parser.parse_args(argv)
    env_path = args.env_file or args.config_dir / "dashboard.env"
    profile_path = args.profile_file or args.config_dir / "dashboard-profile.json"
    if not env_path.exists() or not profile_path.exists():
        parser.error("configuration files do not exist; run the installer first")
    try:
        environment = parse_env_file(env_path)
        profile = load_profile(profile_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.check:
        print("Configuration is valid.")
        for line in _summary(profile, environment):
            print(f"  {line}")
        return 0
    prompts = Prompter()
    print("RV Dashboard configuration wizard")
    print("Private addresses and credentials are written only to the protected installation configuration.")
    print("Wi-Fi credentials remain managed by Raspberry Pi OS.")
    try:
        updated_profile, env_updates = build_configuration(profile, environment, prompts)
        preview_environment = {**environment, **env_updates}
        print("\nConfiguration summary")
        for line in _summary(updated_profile, preview_environment):
            print(f"  {line}")
        if not prompts.yes_no("Write this configuration?", True):
            print("No files were changed.")
            return 0
        write_profile(profile_path, updated_profile)
        update_env_file(env_path, env_updates)
    except (EOFError, KeyboardInterrupt):
        print("\nConfiguration canceled; no files were changed.")
        return 130
    except (OSError, ValueError) as exc:
        print(f"Configuration failed: {exc}")
        return 1
    print("Configuration saved.")
    print("Sensor mappings remain separate and were not changed.")
    return 0


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
