from datetime import UTC, datetime, timedelta

from rv_dashboard.model import Health, Reading, Snapshot
from rv_dashboard.normalization import FieldRule, Normalizer


def test_vendor_fields_are_normalized_without_leaking_names():
    normalizer = Normalizer([
        FieldRule("Dog Area", "DegreesF", "environment.dog.temperature", "°F", "number")
    ])
    payload = {"latest_points": [{"TimeStamp": 1_700_000_000, "DegreesF": "73.5", "IgnoredVendorField": 99}]}
    readings = normalizer.normalize("Dog Area", payload)
    assert len(readings) == 1
    assert readings[0].path == "environment.dog.temperature"
    assert readings[0].value == 73.5


def test_old_reading_is_never_reported_as_current():
    old = datetime.now(UTC) - timedelta(minutes=10)
    snapshot = Snapshot({"power.battery.soc": Reading("power.battery.soc", 87, "%", old, "test")})
    api = snapshot.to_api(stale_after_seconds=150)
    assert api["readings"]["power.battery.soc"]["health"] == Health.STALE.value
    assert api["overall_health"] == Health.STALE.value
