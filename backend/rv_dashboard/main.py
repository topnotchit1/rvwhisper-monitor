from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .collector import Collector
from .demo import demo_snapshot
from .event_bus import EventBus
from .model import Snapshot
from .normalization import Normalizer
from .operator_auth import OperatorPinGuard
from .profile import load_profile
from .rvwhisper import (
    AlertAcknowledgementError,
    AlertAcknowledgementStale,
    AlertAcknowledgementUncertain,
    client_from_environment,
)
from .store import Store


ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = int(os.getenv("RVW_POLL_SECONDS", "60"))
STALE_AFTER_SECONDS = int(os.getenv("STALE_AFTER_SECONDS", str(max(POLL_SECONDS * 2 + 15, 150))))
MODE = os.getenv("DASHBOARD_MODE", "demo").lower()
ALLOW_ALERT_ACK = os.getenv("ALLOW_ALERT_ACK", "false").casefold() == "true"
OPERATOR_PIN_HASH = os.getenv("DASHBOARD_OPERATOR_PIN_HASH", "")
PROFILE = load_profile(os.getenv("DASHBOARD_PROFILE"))
CLIMATE_PATHS = [item["path"] for item in PROFILE["sections"]["climate"]["items"]]
CLIMATE_HUMIDITY_PATHS = [path.removesuffix(".temperature") + ".humidity" for path in CLIMATE_PATHS]
HISTORY_PATHS = [
    "power.battery.soc",
    "power.battery.voltage",
    "power.battery.current",
    "power.battery.power",
    "power.ac.voltage",
    "power.ac.current",
    "power.ac.power",
    "power.ac.frequency",
    "power.ac.energy_kwh",
    "power.ac.rssi",
] + CLIMATE_PATHS + CLIMATE_HUMIDITY_PATHS + [item["path"] for item in PROFILE["sections"]["tanks"]["items"]]

snapshot = demo_snapshot() if MODE != "live" else Snapshot(collector_online=False)
bus = EventBus()
store = Store(os.getenv("DASHBOARD_DB", str(ROOT / "data" / "dashboard.db")))
if MODE == "live":
    snapshot.merge(store.current_readings())
collector: Collector | None = None
operator_pin_guard = OperatorPinGuard()


class AlertAcknowledgementRequest(BaseModel):
    confirmation: Literal["stop-repeat-notifications"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global collector
    task: asyncio.Task[None] | None = None
    if MODE == "live":
        normalizer = Normalizer.from_file(os.getenv("SENSOR_MAP", str(ROOT / "config" / "sensor-map.json")))
        try:
            client = client_from_environment()
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        collector = Collector(client, normalizer, snapshot, store, bus, POLL_SECONDS, STALE_AFTER_SECONDS)
        if ALLOW_ALERT_ACK:
            if client.access_mode != "local" or not client.has_local_alert_credentials:
                raise RuntimeError("Alert acknowledgement requires authenticated local RVM3 access")
            if not OPERATOR_PIN_HASH:
                raise RuntimeError("Alert acknowledgement requires DASHBOARD_OPERATOR_PIN_HASH")
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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Dashboard-Operator-PIN"],
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": MODE,
        "collector_online": snapshot.collector_online,
        "collector_last_success_at": (
            snapshot.collector_last_success_at.isoformat() if snapshot.collector_last_success_at else None
        ),
        "collector_error": snapshot.collector_error,
    }


@app.get("/api/state")
async def get_state() -> dict[str, object]:
    return snapshot.to_api(STALE_AFTER_SECONDS) | {"mode": MODE}


@app.get("/api/config")
async def get_config() -> dict[str, object]:
    """Return display-only installation settings; secrets and network details are never exposed."""
    return PROFILE | {"capabilities": {"alert_acknowledgement": ALLOW_ALERT_ACK and MODE == "live"}}


@app.get("/api/events")
async def get_events(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, object]]:
    return store.recent_events(limit)


@app.get("/api/alerts")
async def get_alerts() -> dict[str, object]:
    active = store.active_alerts()
    return {
        "active": active,
        "unacknowledged": sum(not alert["acknowledged"] for alert in active),
        "acknowledged": sum(bool(alert["acknowledged"]) for alert in active),
    }


@app.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    command: AlertAcknowledgementRequest,
    http_request: Request,
    operator_pin: str | None = Header(default=None, alias="X-Dashboard-Operator-PIN"),
) -> dict[str, object]:
    """Request one verified RVM3 acknowledgement without exposing vendor credentials."""
    if not ALLOW_ALERT_ACK or MODE != "live" or collector is None:
        raise HTTPException(status_code=404, detail="Alert acknowledgement is not enabled")
    client_host = http_request.client.host if http_request.client else ""
    if client_host not in {"127.0.0.1", "::1"}:
        store.add_event(
            "dashboard.alert.acknowledgement.denied",
            "warning",
            "Alert acknowledgement denied",
            "Control request did not originate on the dashboard device",
            {"alert_id": alert_id},
        )
        raise HTTPException(status_code=403, detail="Acknowledgement is available only on the dashboard device")
    auth_result = operator_pin_guard.check(operator_pin or "", OPERATOR_PIN_HASH)
    if auth_result != "allowed":
        store.add_event(
            "dashboard.alert.acknowledgement.denied",
            "warning",
            "Alert acknowledgement denied",
            "Operator PIN was rejected" if auth_result == "denied" else "Operator PIN attempts are temporarily locked",
            {"alert_id": alert_id},
        )
        raise HTTPException(
            status_code=429 if auth_result == "locked" else 401,
            detail="Too many invalid PIN attempts; try again later" if auth_result == "locked" else "Invalid operator PIN",
        )

    current = store.active_alert(alert_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Alert is no longer active")
    request_id = uuid.uuid4().hex
    store.add_event(
        "dashboard.alert.acknowledgement.requested",
        "warning",
        str(current["title"]),
        "Local operator requested acknowledgement; awaiting RV Whisper confirmation",
        {"alert_id": alert_id, "request_id": request_id},
    )
    try:
        result = await collector.client.acknowledge_alert(alert_id)
    except AlertAcknowledgementStale as exc:
        store.add_event(
            "dashboard.alert.acknowledgement.stale",
            "warning",
            str(current["title"]),
            "Request stopped because the alert instance changed or cleared",
            {"alert_id": alert_id, "request_id": request_id},
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AlertAcknowledgementUncertain as exc:
        store.add_event(
            "dashboard.alert.acknowledgement.uncertain",
            "warning",
            str(current["title"]),
            "One request was sent; authoritative confirmation was unavailable and no retry was attempted",
            {"alert_id": alert_id, "request_id": request_id},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AlertAcknowledgementError as exc:
        store.add_event(
            "dashboard.alert.acknowledgement.failed",
            "warning",
            str(current["title"]),
            "RV Whisper rejected or could not safely process the request",
            {"alert_id": alert_id, "request_id": request_id},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    store.sync_active_alerts(result.active_alerts)
    active = store.active_alerts()
    await bus.publish({"type": "alerts", "alerts": active})
    event_type = (
        "dashboard.alert.acknowledgement.confirmed"
        if result.status == "confirmed"
        else "dashboard.alert.acknowledgement.already_confirmed"
    )
    store.add_event(
        event_type,
        "normal",
        result.alert.title,
        "RV Whisper confirmed acknowledgement"
        if result.status == "confirmed"
        else "RV Whisper had already acknowledged this alert; no duplicate write was sent",
        {"alert_id": alert_id, "request_id": request_id},
    )
    return {
        "status": result.status,
        "request_id": request_id,
        "alert": next((alert for alert in active if alert["id"] == alert_id), None),
    }


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
