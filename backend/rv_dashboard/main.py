from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .collector import Collector
from .demo import demo_snapshot
from .event_bus import EventBus
from .model import Snapshot
from .normalization import Normalizer
from .rvwhisper import RVWhisperClient
from .store import Store


ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = int(os.getenv("RVW_POLL_SECONDS", "60"))
STALE_AFTER_SECONDS = int(os.getenv("STALE_AFTER_SECONDS", str(max(POLL_SECONDS * 2 + 15, 150))))
MODE = os.getenv("DASHBOARD_MODE", "demo").lower()
CLIMATE_PATHS = [
    "environment.dog.temperature",
    "environment.coach.temperature",
    "environment.fridge.temperature",
    "environment.freezer.temperature",
]
HISTORY_PATHS = [
    "power.battery.soc",
    "power.battery.voltage",
    "power.battery.current",
    "power.battery.power",
    "power.ac.voltage",
    "power.ac.current",
    "power.ac.power",
    "power.ac.frequency",
    "environment.dog.temperature",
    "environment.dog.humidity",
    "environment.coach.temperature",
    "environment.coach.humidity",
    "environment.fridge.temperature",
    "environment.fridge.humidity",
    "environment.freezer.temperature",
    "environment.freezer.humidity",
    "tank.fresh.percent",
    "tank.gray.percent",
    "tank.black.percent",
    "tank.propane.percent",
]

snapshot = demo_snapshot() if MODE != "live" else Snapshot()
bus = EventBus()
store = Store(os.getenv("DASHBOARD_DB", str(ROOT / "data" / "dashboard.db")))
collector: Collector | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global collector
    task: asyncio.Task[None] | None = None
    if MODE == "live":
        required = {key: os.getenv(key) for key in ("RVW_ID", "RVW_USERNAME", "RVW_PASSWORD")}
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Live mode requires: {', '.join(missing)}")
        normalizer = Normalizer.from_file(os.getenv("SENSOR_MAP", str(ROOT / "config" / "sensor-map.json")))
        client = RVWhisperClient(required["RVW_ID"] or "", required["RVW_USERNAME"] or "", required["RVW_PASSWORD"] or "")
        collector = Collector(client, normalizer, snapshot, store, bus, POLL_SECONDS, STALE_AFTER_SECONDS)
        task = asyncio.create_task(collector.run(), name="rvwhisper-collector")
    try:
        yield
    finally:
        if collector:
            await collector.stop()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        store.close()


app = FastAPI(title="Minnie Winnie Dashboard API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("DASHBOARD_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "mode": MODE, "collector_online": snapshot.collector_online}


@app.get("/api/state")
async def get_state() -> dict[str, object]:
    return snapshot.to_api(STALE_AFTER_SECONDS) | {"mode": MODE}


@app.get("/api/events")
async def get_events(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, object]]:
    return store.recent_events(limit)


@app.get("/api/climate-summary")
async def get_climate_summary(hours: int = Query(24, ge=1, le=72)) -> dict[str, object]:
    return {"hours": hours, "readings": store.numeric_ranges(CLIMATE_PATHS, hours)}


@app.get("/api/history-summary")
async def get_history_summary(hours: int = Query(24, ge=1, le=72)) -> dict[str, object]:
    """Return real retained ranges for every numeric dashboard detail field."""
    return {"hours": hours, "readings": store.numeric_ranges(HISTORY_PATHS, hours)}


@app.get("/api/stream")
async def stream_state() -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        yield f"event: state\ndata: {json.dumps(snapshot.to_api(STALE_AFTER_SECONDS) | {'mode': MODE})}\n\n"
        async with bus.subscriber() as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25)
                    if event.get("type") == "state" and isinstance(event.get("state"), dict):
                        event["state"]["mode"] = MODE
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def run() -> None:
    import uvicorn
    uvicorn.run("rv_dashboard.main:app", host="0.0.0.0", port=int(os.getenv("DASHBOARD_API_PORT", "8080")), reload=False)
