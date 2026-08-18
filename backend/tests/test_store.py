from datetime import UTC, datetime, timedelta

from rv_dashboard.model import Reading
from rv_dashboard.store import Store


def test_store_upserts_current_and_appends_history(tmp_path):
    store = Store(tmp_path / "dashboard.db")
    reading = Reading("power.battery.soc", 87, "%", datetime.now(UTC), "test")
    store.save_readings([reading])
    store.save_readings([reading])
    store.add_event("test", "normal", "Saved reading")
    assert store.recent_events(1)[0]["title"] == "Saved reading"
    store.close()


def test_store_calculates_numeric_ranges_from_retained_history(tmp_path):
    store = Store(tmp_path / "dashboard.db")
    now = datetime.now(UTC)
    path = "environment.dog.temperature"
    store.save_readings([
        Reading(path, 71, "°F", now - timedelta(hours=23), "test"),
        Reading(path, 76, "°F", now - timedelta(hours=2), "test"),
        Reading(path, 73, "°F", now, "test"),
        Reading(path, 99, "°F", now - timedelta(hours=25), "test"),
    ])
    summary = store.numeric_ranges([path], 24)[path]
    assert summary["min"] == 71
    assert summary["max"] == 76
    assert summary["samples"] == 3
    store.close()
