from __future__ import annotations

from datetime import UTC, datetime

from .model import Reading, Snapshot


def demo_snapshot() -> Snapshot:
    now = datetime.now(UTC)
    values = {
        "power.battery.soc": (87, "%", "powermon-5s"),
        "power.battery.voltage": (13.1, "V", "powermon-5s"),
        "power.battery.current": (42, "A", "powermon-5s"),
        "power.battery.power": (543, "W", "powermon-5s"),
        "power.ac.connected": (True, None, "hughes-pwd30"),
        "power.ac.voltage": (121, "V", "hughes-pwd30"),
        "power.ac.current": (8.4, "A", "hughes-pwd30"),
        "power.ac.frequency": (60.0, "Hz", "hughes-pwd30"),
        "environment.front_room.temperature": (73, "°F", "bth1-front-room"),
        "environment.bedroom.temperature": (74, "°F", "bth1-bedroom"),
        "environment.fridge.temperature": (37, "°F", "bth1-fridge"),
        "environment.freezer.temperature": (4, "°F", "bth1-freezer"),
        "tank.fresh.percent": (74, "%", "demo"),
        "tank.gray.percent": (18, "%", "demo"),
        "tank.black.percent": (12, "%", "demo"),
        "tank.propane.percent": (68, "%", "demo"),
        "network.internet.online": (True, None, "host"),
        "network.rvwhisper.online": (True, None, "collector"),
    }
    return Snapshot({path: Reading(path, value, unit, now, source) for path, (value, unit, source) in values.items()})
