from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from rv_dashboard.alerts import ActiveAlert
from rv_dashboard.operator_auth import hash_operator_pin
from rv_dashboard.rvwhisper import AlertAcknowledgementResult


@pytest.mark.asyncio
async def test_acknowledgement_endpoint_requires_pin_and_audits_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    monkeypatch.setenv("DASHBOARD_MODE", "live")
    monkeypatch.setenv("ALLOW_ALERT_ACK", "true")
    monkeypatch.setenv("DASHBOARD_OPERATOR_PIN_HASH", hash_operator_pin("4826"))
    import rv_dashboard.main as main

    try:
        main.store.close()
    except Exception:
        pass
    main = importlib.reload(main)
    unacknowledged = ActiveAlert("a1", "Test", False, "2026-09-01T08:22:00", "4815")
    acknowledged = ActiveAlert("a1", "Test", True, "2026-09-01T08:22:00")
    main.store.sync_active_alerts([unacknowledged])

    class FakeClient:
        async def acknowledge_alert(self, alert_id: str) -> AlertAcknowledgementResult:
            assert alert_id == "a1"
            return AlertAcknowledgementResult("confirmed", acknowledged, [acknowledged])

    main.collector = SimpleNamespace(client=FakeClient())
    command = main.AlertAcknowledgementRequest(confirmation="stop-repeat-notifications")
    local_request = Request({"type": "http", "client": ("127.0.0.1", 40000), "headers": []})
    remote_request = Request({"type": "http", "client": ("10.0.194.22", 40000), "headers": []})
    try:
        with pytest.raises(HTTPException) as remote_denied:
            await main.acknowledge_alert("a1", command, remote_request, "4826")
        assert remote_denied.value.status_code == 403

        with pytest.raises(HTTPException) as denied:
            await main.acknowledge_alert("a1", command, local_request, "0000")
        assert denied.value.status_code == 401

        response = await main.acknowledge_alert("a1", command, local_request, "4826")

        assert response["status"] == "confirmed"
        assert response["alert"]["acknowledged"] is True
        event_types = [event["event_type"] for event in main.store.recent_events(10)]
        assert "dashboard.alert.acknowledgement.denied" in event_types
        assert "dashboard.alert.acknowledgement.requested" in event_types
        assert "dashboard.alert.acknowledgement.confirmed" in event_types
    finally:
        main.store.close()
