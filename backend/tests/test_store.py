from datetime import UTC, datetime

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
