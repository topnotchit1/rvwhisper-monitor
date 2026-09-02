from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from .alerts import ActiveAlert
from .model import Health, Reading


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS current_state (
        path TEXT PRIMARY KEY,
        value_json TEXT,
        unit TEXT,
        observed_at TEXT NOT NULL,
        source TEXT NOT NULL,
        health TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS samples (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        value_json TEXT,
        unit TEXT,
        observed_at TEXT NOT NULL,
        source TEXT NOT NULL,
        health TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_samples_path_observed_at
        ON samples(path, observed_at DESC)""",
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT,
        occurred_at TEXT NOT NULL,
        data_json TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_events_occurred_at
        ON events(occurred_at DESC)""",
    """CREATE TABLE IF NOT EXISTS active_alerts (
        fingerprint TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        acknowledged INTEGER NOT NULL,
        created_at TEXT,
        last_seen_at TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_active_alerts_acknowledged
        ON active_alerts(acknowledged, created_at DESC)""",
)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            for statement in SCHEMA:
                self._connection.execute(statement)
            self._connection.execute("PRAGMA optimize")

    def save_readings(self, readings: list[Reading]) -> None:
        with self._lock, self._connection:
            for reading in readings:
                values = (reading.path, json.dumps(reading.value), reading.unit, reading.observed_at.isoformat(), reading.source, reading.health.value)
                self._connection.execute(
                    """INSERT INTO current_state(path, value_json, unit, observed_at, source, health)
                       VALUES(?, ?, ?, ?, ?, ?)
                       ON CONFLICT(path) DO UPDATE SET value_json=excluded.value_json,
                       unit=excluded.unit, observed_at=excluded.observed_at,
                       source=excluded.source, health=excluded.health""",
                    values,
                )
                self._connection.execute(
                    "INSERT INTO samples(path, value_json, unit, observed_at, source, health) VALUES(?, ?, ?, ?, ?, ?)",
                    values,
                )

    def current_readings(self) -> list[Reading]:
        """Restore the last known snapshot after a dashboard process restart."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT path, value_json, unit, observed_at, source, health FROM current_state"
            ).fetchall()
        readings: list[Reading] = []
        for row in rows:
            try:
                observed_at = datetime.fromisoformat(row["observed_at"])
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=UTC)
                readings.append(
                    Reading(
                        row["path"],
                        json.loads(row["value_json"]),
                        row["unit"],
                        observed_at,
                        row["source"],
                        Health(row["health"]),
                    )
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return readings

    def add_event(self, event_type: str, severity: str, title: str, detail: str = "", data: dict[str, Any] | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO events(event_type, severity, title, detail, occurred_at, data_json) VALUES(?, ?, ?, ?, ?, ?)",
                (event_type, severity, title, detail, datetime.now(UTC).isoformat(), json.dumps(data or {})),
            )

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM events ORDER BY occurred_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        return [dict(row) | {"data": json.loads(row["data_json"] or "{}") } for row in rows]

    def sync_active_alerts(self, alerts: list[ActiveAlert]) -> bool:
        """Mirror RV Whisper's active list and retain local transition history."""
        now = datetime.now(UTC).isoformat()
        incoming = {alert.fingerprint: alert for alert in alerts}
        changed = False
        with self._lock, self._connection:
            existing = {
                row["fingerprint"]: row
                for row in self._connection.execute("SELECT * FROM active_alerts").fetchall()
            }
            for fingerprint, alert in incoming.items():
                previous = existing.get(fingerprint)
                acknowledged = int(alert.acknowledged)
                self._connection.execute(
                    """INSERT INTO active_alerts(fingerprint, title, acknowledged, created_at, last_seen_at)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(fingerprint) DO UPDATE SET title=excluded.title,
                       acknowledged=excluded.acknowledged, created_at=excluded.created_at,
                       last_seen_at=excluded.last_seen_at""",
                    (fingerprint, alert.title, acknowledged, alert.created_at, now),
                )
                if previous is None:
                    changed = True
                    self._insert_event(
                        "rvwhisper.alert.active",
                        "normal" if alert.acknowledged else "warning",
                        alert.title,
                        "Active alert imported from RV Whisper" + (" · acknowledged" if alert.acknowledged else " · needs attention"),
                        now,
                        {"alert_id": fingerprint, "acknowledged": alert.acknowledged},
                    )
                elif bool(previous["acknowledged"]) != alert.acknowledged:
                    changed = True
                    self._insert_event(
                        "rvwhisper.alert.acknowledged" if alert.acknowledged else "rvwhisper.alert.reopened",
                        "normal" if alert.acknowledged else "warning",
                        alert.title,
                        "Acknowledged in RV Whisper" if alert.acknowledged else "Requires attention in RV Whisper",
                        now,
                        {"alert_id": fingerprint, "acknowledged": alert.acknowledged},
                    )
            for fingerprint, previous in existing.items():
                if fingerprint in incoming:
                    continue
                changed = True
                self._connection.execute("DELETE FROM active_alerts WHERE fingerprint = ?", (fingerprint,))
                self._insert_event(
                    "rvwhisper.alert.resolved",
                    "normal",
                    previous["title"],
                    "Trigger condition cleared in RV Whisper",
                    now,
                    {"alert_id": fingerprint},
                )
        return changed

    def active_alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT fingerprint AS id, title, acknowledged, created_at, last_seen_at
                   FROM active_alerts
                   ORDER BY acknowledged ASC, created_at DESC"""
            ).fetchall()
        return [dict(row) | {"acknowledged": bool(row["acknowledged"])} for row in rows]

    def active_alert(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT fingerprint AS id, title, acknowledged, created_at, last_seen_at
                   FROM active_alerts WHERE fingerprint = ?""",
                (fingerprint,),
            ).fetchone()
        return None if row is None else dict(row) | {"acknowledged": bool(row["acknowledged"])}

    def _insert_event(
        self,
        event_type: str,
        severity: str,
        title: str,
        detail: str,
        occurred_at: str,
        data: dict[str, Any],
    ) -> None:
        self._connection.execute(
            "INSERT INTO events(event_type, severity, title, detail, occurred_at, data_json) VALUES(?, ?, ?, ?, ?, ?)",
            (event_type, severity, title, detail, occurred_at, json.dumps(data)),
        )

    def numeric_ranges(self, paths: list[str], hours: int = 24) -> dict[str, dict[str, Any]]:
        """Return real min/max values from retained samples for the requested time window."""
        if not paths:
            return {}
        cutoff = (datetime.now(UTC) - timedelta(hours=max(1, min(hours, 72)))).isoformat()
        placeholders = ",".join("?" for _ in paths)
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT path, value_json, unit, observed_at
                    FROM samples
                    WHERE path IN ({placeholders}) AND observed_at >= ?
                    ORDER BY path, observed_at DESC""",
                (*paths, cutoff),
            ).fetchall()

        summaries: dict[str, dict[str, Any]] = {}
        for row in rows:
            value = json.loads(row["value_json"])
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            summary = summaries.setdefault(
                row["path"],
                {"min": value, "max": value, "unit": row["unit"], "samples": 0, "latest_at": row["observed_at"]},
            )
            summary["min"] = min(summary["min"], value)
            summary["max"] = max(summary["max"], value)
            summary["samples"] += 1
        return summaries

    def prune_high_resolution(self, hours: int = 72) -> int:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM samples WHERE observed_at < ?", (cutoff,))
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
