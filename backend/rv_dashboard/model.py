from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Health(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Reading:
    path: str
    value: bool | float | int | str | None
    unit: str | None
    observed_at: datetime
    source: str
    health: Health = Health.NORMAL
    stale_after_seconds: int | None = None

    def to_api(self, stale_after_seconds: int, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        age = max(0, int((now - self.observed_at).total_seconds()))
        effective_stale_after = self.stale_after_seconds or stale_after_seconds
        health = Health.STALE if age > effective_stale_after else self.health
        result = asdict(self)
        result["observed_at"] = self.observed_at.isoformat()
        result["health"] = health.value
        result["age_seconds"] = age
        result.pop("stale_after_seconds", None)
        return result


@dataclass
class Snapshot:
    readings: dict[str, Reading] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    collector_online: bool = True

    def merge(self, incoming: list[Reading]) -> list[Reading]:
        changed: list[Reading] = []
        for reading in incoming:
            previous = self.readings.get(reading.path)
            self.readings[reading.path] = reading
            if previous is None or previous.value != reading.value or previous.health != reading.health:
                changed.append(reading)
        self.generated_at = datetime.now(UTC)
        return changed

    def to_api(self, stale_after_seconds: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        readings = {path: reading.to_api(stale_after_seconds, now) for path, reading in self.readings.items()}
        states = {item["health"] for item in readings.values()}
        overall = Health.OFFLINE if not self.collector_online else (
            Health.CRITICAL if Health.CRITICAL.value in states else
            Health.WARNING if Health.WARNING.value in states else
            Health.STALE if Health.STALE.value in states else
            Health.NORMAL
        )
        return {
            "generated_at": self.generated_at.isoformat(),
            "collector_online": self.collector_online,
            "overall_health": overall.value,
            "readings": readings,
        }
