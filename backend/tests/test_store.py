from datetime import UTC, datetime, timedelta

from rv_dashboard.model import Reading
from rv_dashboard.alerts import ActiveAlert
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


def test_store_tracks_alert_acknowledgement_and_resolution(tmp_path):
    store = Store(tmp_path / "dashboard.db")
    alert = ActiveAlert("a1", "Freezer is warm", False, "2026-08-20T20:00:00")
    assert store.sync_active_alerts([alert]) is True
    assert store.active_alerts()[0]["acknowledged"] is False
    assert store.active_alert("a1")["title"] == "Freezer is warm"
    assert store.active_alert("missing") is None
    assert store.sync_active_alerts([alert]) is False

    acknowledged = ActiveAlert("a1", "Freezer is warm", True, "2026-08-20T20:00:00")
    assert store.sync_active_alerts([acknowledged]) is True
    assert store.active_alerts()[0]["acknowledged"] is True
    assert store.sync_active_alerts([]) is True
    assert store.active_alerts() == []
    assert [event["event_type"] for event in store.recent_events(3)] == [
        "rvwhisper.alert.resolved",
        "rvwhisper.alert.acknowledged",
        "rvwhisper.alert.active",
    ]
    store.close()
