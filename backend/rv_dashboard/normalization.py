from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .model import Health, Reading


def _identity(value: Any) -> Any:
    return value


def _number(value: Any) -> float:
    return float(value)


def _integer(value: Any) -> int:
    return int(float(value))


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "connected",
        "open",
        "up",
        "online",
        "active",
    }


TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "identity": _identity,
    "number": _number,
    "integer": _integer,
    "boolean": _boolean,
    "invert_boolean": lambda value: not _boolean(value),
    "ac_connected": lambda value: float(value) >= 90,
}


@dataclass(frozen=True)
class FieldRule:
    sensor: str
    field: str
    path: str
    unit: str | None = None
    transform: str = "identity"
    stale_after_seconds: int | None = None


class Normalizer:
    """Translate observed vendor payloads into stable application paths.

    Rules are configuration, not guesses in application code. New sensor payloads
    should be captured first and then mapped explicitly in sensor-map.json.
    """

    def __init__(self, rules: list[FieldRule]):
        self.rules = rules

    @classmethod
    def from_file(cls, path: str | Path) -> "Normalizer":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([FieldRule(**rule) for rule in raw["rules"]])

    def normalize(self, sensor_name: str, payload: dict[str, Any]) -> list[Reading]:
        points = payload.get("latest_points")
        if not isinstance(points, list) or not points:
            return []
        row = points[-1]
        if not isinstance(row, dict):
            return []
        observed_at = self._timestamp(row.get("TimeStamp"))
        readings: list[Reading] = []
        for rule in self.rules:
            if rule.sensor.casefold() != sensor_name.casefold() or rule.field not in row:
                continue
            stale_after_seconds = rule.stale_after_seconds
            if stale_after_seconds is None and rule.path.startswith("environment."):
                stale_after_seconds = 420
            try:
                value = TRANSFORMS[rule.transform](row[rule.field])
            except (KeyError, TypeError, ValueError):
                readings.append(Reading(rule.path, None, rule.unit, observed_at, f"rvwhisper:{sensor_name}", Health.UNKNOWN, stale_after_seconds))
                continue
            readings.append(Reading(rule.path, value, rule.unit, observed_at, f"rvwhisper:{sensor_name}", stale_after_seconds=stale_after_seconds))
        return readings

    @staticmethod
    def _timestamp(raw: Any) -> datetime:
        if raw is None:
            return datetime.now(UTC)
        try:
            value = float(raw)
            if value > 10_000_000_000:
                value /= 1000
            return datetime.fromtimestamp(value, UTC)
        except (TypeError, ValueError, OSError):
            return datetime.now(UTC)
