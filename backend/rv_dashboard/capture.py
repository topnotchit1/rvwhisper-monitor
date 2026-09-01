from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from .envfile import load_env_file as _load_env_file
from .rvwhisper import client_from_environment


ROOT = Path(__file__).resolve().parents[1]
def load_env_file(path: Path) -> None:
    """Load the simple KEY=VALUE format used by the protected Pi environment file."""
    _load_env_file(path)


def safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:60] or fallback


async def capture(output_root: Path, include_alerts: bool = False) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    capture_dir = output_root.expanduser().resolve() / stamp
    capture_dir.mkdir(parents=True, mode=0o700)
    capture_dir.chmod(0o700)

    try:
        client = client_from_environment()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    manifest: list[dict[str, object]] = []
    try:
        sensors = await client.authenticate()
        for index, sensor in enumerate(sensors, start=1):
            payload = await client.fetch_sensor(sensor)
            filename = f"{index:02d}-{safe_name(sensor.name, f'sensor-{index:02d}')}.json"
            destination = capture_dir / filename
            destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            destination.chmod(0o600)
            manifest.append({
                "sensor": sensor.name,
                "file": filename,
                "top_level_fields": sorted(payload.keys()),
            })
        if include_alerts:
            alert_page = await client.fetch_alert_settings()
            alert_path = capture_dir / "alert-settings.html"
            alert_path.write_text(alert_page, encoding="utf-8")
            alert_path.chmod(0o600)
    finally:
        await client.close()

    manifest_path = capture_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"captured_at": stamp, "sensors": manifest}, indent=2) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    return capture_dir


def run() -> None:
    parser = argparse.ArgumentParser(description="Capture private RV Whisper payloads for local sensor mapping.")
    parser.add_argument("--env-file", type=Path, help="Protected KEY=VALUE file containing RV Whisper credentials.")
    parser.add_argument("--output", type=Path, help="Private output directory; a timestamped folder is created inside it.")
    parser.add_argument("--include-alerts", action="store_true", help="Also capture the private active-alert page for parser development.")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
    output = args.output or Path(os.getenv("RVW_CAPTURE_DIR", str(ROOT / "captures")))
    capture_dir = asyncio.run(capture(output, include_alerts=args.include_alerts))
    print(f"Captured private payloads in {capture_dir}")
    print("Do not commit or upload these files until they have been reviewed and redacted.")


if __name__ == "__main__":
    run()
