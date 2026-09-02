from __future__ import annotations

import asyncio
import logging

import httpx

from .alerts import AlertParseError, parse_active_alerts, parse_sensor_active_alerts
from .event_bus import EventBus
from .model import Snapshot
from .normalization import Normalizer
from .rvwhisper import LocalAlertAuthenticationError, RVWhisperClient, RVWhisperError
from .store import Store

LOGGER = logging.getLogger(__name__)


def describe_collector_failure(exc: Exception) -> dict[str, str]:
    """Return a useful, display-safe failure without leaking URLs or credentials."""
    if isinstance(exc, httpx.ConnectTimeout):
        return {"code": "connect_timeout", "message": "Connection to RV Whisper timed out"}
    if isinstance(exc, httpx.ReadTimeout):
        return {"code": "read_timeout", "message": "RV Whisper did not finish responding"}
    if isinstance(exc, httpx.RemoteProtocolError):
        return {"code": "response_interrupted", "message": "RV Whisper interrupted its response"}
    if isinstance(exc, httpx.HTTPStatusError):
        return {"code": "http_error", "message": f"RV Whisper returned HTTP {exc.response.status_code}"}
    if isinstance(exc, httpx.ConnectError) or isinstance(exc, OSError):
        return {"code": "unreachable", "message": "RV Whisper is unreachable on the network"}
    if isinstance(exc, LocalAlertAuthenticationError):
        return {"code": "authentication_failed", "message": "RV Whisper local authentication failed"}
    if isinstance(exc, RVWhisperError):
        return {"code": "vendor_error", "message": str(exc).strip() or "RV Whisper returned unusable data"}
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return {"code": "timeout", "message": "RV Whisper request timed out"}
    return {"code": "unknown", "message": "RV Whisper collection failed"}


def next_failure_backoff(access_mode: str, poll_seconds: int, current: int) -> int:
    """Retry a local RVM3 promptly; retain conservative gateway backoff."""
    if access_mode == "local":
        return min(max(poll_seconds, 30), 60)
    return min(max(current * 2, 60), 900)


class Collector:
    def __init__(
        self,
        client: RVWhisperClient,
        normalizer: Normalizer,
        snapshot: Snapshot,
        store: Store,
        bus: EventBus,
        poll_seconds: int = 60,
        stale_after_seconds: int = 150,
    ):
        self.client = client
        self.normalizer = normalizer
        self.snapshot = snapshot
        self.store = store
        self.bus = bus
        self.poll_seconds = max(30, poll_seconds)
        self.stale_after_seconds = stale_after_seconds
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        backoff = self.poll_seconds
        sensors = None
        while not self._stopped.is_set():
            try:
                if sensors is None:
                    sensors = await self.client.authenticate()
                readings = []
                for sensor in sensors:
                    payload = await self.client.fetch_sensor(sensor)
                    readings.extend(self.normalizer.normalize(sensor.name, payload))
                changed = self.snapshot.merge(readings)
                self.snapshot.mark_collector_online()
                if readings:
                    self.store.save_readings(readings)
                try:
                    try:
                        alert_html = await self.client.fetch_alert_settings()
                        active_alerts = parse_active_alerts(alert_html)
                    except (AlertParseError, LocalAlertAuthenticationError) as exc:
                        if self.client.access_mode != "local":
                            raise
                        LOGGER.warning(
                            "Authenticated RVM3 alert view unavailable; using conservative public fallback: %s",
                            exc,
                        )
                        active_alerts = []
                        for sensor in sensors:
                            sensor_html = await self.client.fetch_sensor_page(sensor)
                            active_alerts.extend(parse_sensor_active_alerts(sensor_html, sensor.id))
                    alerts_changed = self.store.sync_active_alerts(active_alerts)
                    if alerts_changed:
                        await self.bus.publish({"type": "alerts", "alerts": self.store.active_alerts()})
                except (AlertParseError, RVWhisperError, httpx.HTTPError, OSError, TimeoutError) as exc:
                    failure = describe_collector_failure(exc)
                    LOGGER.warning(
                        "RV Whisper alert collection failed without interrupting telemetry: %s",
                        failure["message"],
                    )
                if changed:
                    await self.bus.publish({"type": "state", "state": self.snapshot.to_api(self.stale_after_seconds)})
                backoff = self.poll_seconds
            except (RVWhisperError, httpx.HTTPError, OSError, TimeoutError) as exc:
                failure = describe_collector_failure(exc)
                LOGGER.warning("RV Whisper collection failed: %s", failure["message"])
                sensors = None
                was_online = self.snapshot.collector_online
                self.snapshot.mark_collector_offline(failure)
                if was_online:
                    self.store.add_event(
                        "collector.offline",
                        "warning",
                        "RV Whisper connection interrupted",
                        failure["message"],
                    )
                    await self.bus.publish({"type": "state", "state": self.snapshot.to_api(self.stale_after_seconds)})
                backoff = next_failure_backoff(self.client.access_mode, self.poll_seconds, backoff)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=backoff)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stopped.set()
        await self.client.close()
