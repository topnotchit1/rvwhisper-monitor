from __future__ import annotations

import asyncio
import logging

import httpx

from .event_bus import EventBus
from .model import Snapshot
from .normalization import Normalizer
from .rvwhisper import RVWhisperClient, RVWhisperError
from .store import Store

LOGGER = logging.getLogger(__name__)


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
                self.snapshot.collector_online = True
                if readings:
                    self.store.save_readings(readings)
                if changed:
                    await self.bus.publish({"type": "state", "state": self.snapshot.to_api(self.stale_after_seconds)})
                backoff = self.poll_seconds
            except (RVWhisperError, httpx.HTTPError, OSError, TimeoutError) as exc:
                LOGGER.warning("RV Whisper collection failed: %s", exc)
                sensors = None
                was_online = self.snapshot.collector_online
                self.snapshot.collector_online = False
                if was_online:
                    self.store.add_event("collector.offline", "warning", "RV Whisper connection interrupted", str(exc))
                    await self.bus.publish({"type": "state", "state": self.snapshot.to_api(self.stale_after_seconds)})
                backoff = min(max(backoff * 2, 60), 900)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=backoff)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stopped.set()
        await self.client.close()
