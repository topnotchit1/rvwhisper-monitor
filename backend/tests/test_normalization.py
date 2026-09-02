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


def test_snapshot_reports_safe_collector_diagnostics_and_recovery():
    snapshot = Snapshot(collector_online=False)
    snapshot.mark_collector_offline({"code": "unreachable", "message": "RV Whisper is unreachable on the network"})

    offline = snapshot.to_api(stale_after_seconds=150)
    assert offline["overall_health"] == Health.OFFLINE.value
    assert offline["collector_error"]["code"] == "unreachable"
    assert offline["collector_last_success_at"] is None

    snapshot.mark_collector_online()
    recovered = snapshot.to_api(stale_after_seconds=150)
    assert recovered["collector_online"] is True
    assert recovered["collector_error"] is None
    assert recovered["collector_last_success_at"] is not None


def test_vendor_up_status_is_normalized_as_online():
    normalizer = Normalizer([
        FieldRule("Starlink", "InternetStatus", "network.internet.online", transform="boolean")
    ])
    payload = {"latest_points": [{"TimeStamp": 1_700_000_000, "InternetStatus": "Up"}]}
    readings = normalizer.normalize("Starlink", payload)
    assert readings[0].value is True


def test_slow_sensor_can_define_its_own_freshness_window():
    normalizer = Normalizer([
        FieldRule("WiFi Status", "VPN", "network.rvm3.vpn_online", transform="boolean", stale_after_seconds=900)
    ])
    payload = {"latest_points": [{"TimeStamp": datetime.now(UTC).timestamp() - 600, "VPN": "Up"}]}
    reading = normalizer.normalize("WiFi Status", payload)[0]

    assert reading.to_api(stale_after_seconds=150)["health"] == Health.NORMAL.value


def test_observed_ac_voltage_can_drive_connection_state():
    normalizer = Normalizer([
        FieldRule("Power Watchdog", "Voltage1", "power.ac.connected", transform="ac_connected")
    ])
    connected = normalizer.normalize("Power Watchdog", {"latest_points": [{"Voltage1": "121.2"}]})[0]
    disconnected = normalizer.normalize("Power Watchdog", {"latest_points": [{"Voltage1": "0"}]})[0]

    assert connected.value is True
    assert disconnected.value is False


def test_environment_readings_allow_normal_five_minute_sensor_cadence():
    normalizer = Normalizer([
        FieldRule("Living Area", "DegreesF", "environment.living.temperature", "°F", "number")
    ])
    payload = {"latest_points": [{"TimeStamp": datetime.now(UTC).timestamp() - 300, "DegreesF": "74"}]}
    reading = normalizer.normalize("Living Area", payload)[0]

    assert reading.to_api(stale_after_seconds=150)["health"] == Health.NORMAL.value
