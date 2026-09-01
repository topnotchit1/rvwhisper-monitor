from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .alerts import ActiveAlert, AlertParseError, parse_active_alerts, parse_alert_action_context


class RVWhisperError(RuntimeError):
    pass


class LocalAlertAuthenticationError(RVWhisperError):
    """Device-local alert login failed without affecting LAN telemetry."""


class AlertAcknowledgementError(RVWhisperError):
    """A dashboard acknowledgement could not be safely completed."""


class AlertAcknowledgementStale(AlertAcknowledgementError):
    """The requested dashboard alert no longer identifies one current alert."""


class AlertAcknowledgementUncertain(AlertAcknowledgementError):
    """RV Whisper did not provide authoritative confirmation after one write."""


@dataclass(frozen=True)
class Sensor:
    id: str
    name: str


@dataclass(frozen=True)
class AlertAcknowledgementResult:
    status: str
    alert: ActiveAlert
    active_alerts: list[ActiveAlert]


class RVWhisperClient:
    """Conservative client based on Yeraze/rvwhisper-monitor's public flow.

    RV Whisper does not currently document these web endpoints as a public API.
    Keep polling slow and treat HTML/field changes as recoverable failures.
    """

    GATEWAY_URL = "https://access.rvwhisper.com"

    def __init__(
        self,
        rvm_id: str,
        username: str = "",
        password: str = "",
        timeout_seconds: float = 20,
        *,
        access_mode: str = "gateway",
        base_url: str | None = None,
        system_path: str | None = None,
        local_username: str = "",
        local_password: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if access_mode not in {"gateway", "local"}:
            raise ValueError("RVW_ACCESS_MODE must be 'gateway' or 'local'")
        if access_mode == "gateway" and (not username or not password):
            raise ValueError("Gateway access requires RVW_USERNAME and RVW_PASSWORD")
        if access_mode == "local" and bool(local_username) != bool(local_password):
            raise ValueError("Local alert access requires both RVW_LOCAL_USERNAME and RVW_LOCAL_PASSWORD")
        self.rvm_id = rvm_id
        self.username = username
        self.password = password
        self.local_username = local_username
        self.local_password = local_password
        self.access_mode = access_mode
        self.base_url = (base_url or self.GATEWAY_URL).rstrip("/")
        parsed_url = httpx.URL(self.base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
            raise ValueError("RVW_BASE_URL must be an http:// or https:// origin")
        if parsed_url.path not in {"", "/"} or parsed_url.query or parsed_url.fragment:
            raise ValueError("RVW_BASE_URL must not include a path, query, or fragment")
        default_path = f"/{rvm_id}" if access_mode == "gateway" else ""
        configured_path = default_path if system_path is None else system_path
        self.system_path = f"/{configured_path.strip('/')}" if configured_path.strip("/") else ""
        self._nonce: str | None = None
        self._alert_action_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )
        self._local_alert_client = (
            httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout_seconds,
                follow_redirects=True,
                transport=transport,
            )
            if access_mode == "local" and local_username and local_password
            else None
        )

    async def close(self) -> None:
        if self._local_alert_client is not None:
            await self._local_alert_client.aclose()
        await self._client.aclose()

    async def authenticate(self) -> list[Sensor]:
        if self.access_mode == "local":
            return await self.discover_sensors()
        login_page = await self._client.get("/")
        login_page.raise_for_status()
        csrf_value = self._extract(login_page.text, r'name="csrf_value"\s+value="([^\"]+)"', "csrf_value")
        csrf_name = self._extract(login_page.text, r'name="csrf_name"\s+value="([^\"]+)"', "csrf_name")
        response = await self._client.post("/account/login", data={
            "csrf_value": csrf_value,
            "csrf_name": csrf_name,
            "user_name": self.username,
            "password": self.password,
            "rememberme": "0",
        })
        response.raise_for_status()
        return await self.discover_sensors()

    async def discover_sensors(self) -> list[Sensor]:
        dashboard = await self._client.get(self.system_path or "/")
        dashboard.raise_for_status()
        nonce_match = re.search(r'"ajax_nonce":"([\w-]+)"', dashboard.text, re.IGNORECASE)
        if nonce_match:
            self._nonce = nonce_match.group(1)
        elif self.access_mode == "gateway":
            raise RVWhisperError("Could not find ajax_nonce; the RV Whisper page may have changed")
        else:
            self._nonce = ""
        matches = re.finditer(r'sensor\?sensor_id=(\d+)"\s+title="([^\"]+)"', dashboard.text)
        sensors = [Sensor(match.group(1), match.group(2).strip()) for match in matches]
        if not sensors:
            raise RVWhisperError("No sensors were discovered in the RV Whisper dashboard")
        return sensors

    async def fetch_sensor(self, sensor: Sensor, interval_hours: int = 1, retry_auth: bool = True) -> dict[str, Any]:
        if self._nonce is None:
            await self.authenticate()
        response = await self._client.post(f"{self.system_path}/wp-admin/admin-ajax.php", data={
            "action": "get_latest_data_by_date",
            "sensor": sensor.id,
            "date_interval": str(interval_hours),
            "browser_gmt_offset": "0",
            "charting": "false",
            "bt_nonce": self._nonce or "",
        })
        if response.status_code in {401, 403} and retry_auth and self.access_mode == "gateway":
            await self.authenticate()
            return await self.fetch_sensor(sensor, interval_hours, retry_auth=False)
        if response.status_code in {401, 403}:
            raise RVWhisperError("RV Whisper rejected the refreshed session")
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            self._nonce = None
            raise RVWhisperError(f"RV Whisper returned non-JSON data for {sensor.name}") from exc

    async def fetch_alert_settings(self, retry_auth: bool = True) -> str:
        """Return the read-only RV Whisper alert page for local parsing.

        RV Whisper does not publish an alert API, so the collector treats this
        HTML as vendor input and never posts acknowledgement or configuration
        changes back to the service.
        """
        alert_client = self._local_alert_client or self._client
        response = await alert_client.get(f"{self.system_path}/alert-settings/")
        if (
            self.access_mode == "local"
            and self.has_local_alert_credentials
            and (
                response.status_code in {401, 403}
                or self._is_login_response(response)
                or not self._has_alert_view(response.text)
            )
        ):
            if retry_auth:
                return await self._authenticate_local_alerts()
            raise LocalAlertAuthenticationError("RVM3 local alert authentication expired")
        if response.status_code in {401, 403} and retry_auth and self.access_mode == "gateway":
            await self.authenticate()
            return await self.fetch_alert_settings(retry_auth=False)
        if response.status_code in {401, 403}:
            raise RVWhisperError("RV Whisper rejected the refreshed alert session")
        response.raise_for_status()
        return response.text

    @property
    def has_local_alert_credentials(self) -> bool:
        return bool(self.local_username and self.local_password)

    @staticmethod
    def _is_login_response(response: httpx.Response) -> bool:
        path = response.url.path.rstrip("/").casefold()
        if path.endswith("/wp-login.php"):
            return True
        return bool(
            re.search(r'<form[^>]+id=["\']loginform["\']', response.text, re.IGNORECASE)
            or (
                re.search(r'name=["\']log["\']', response.text, re.IGNORECASE)
                and re.search(r'name=["\']pwd["\']', response.text, re.IGNORECASE)
            )
        )

    @staticmethod
    def _has_alert_view(html: str) -> bool:
        return bool(re.search(r'id=["\']view-alerts["\']', html, re.IGNORECASE))

    async def _authenticate_local_alerts(self) -> str:
        """Authenticate only the local alert session using device credentials.

        Telemetry remains available through the anonymous LAN endpoints. Cloud
        credentials are intentionally never reused for this WordPress login.
        """
        if not self.has_local_alert_credentials:
            raise LocalAlertAuthenticationError("RVM3 local alert credentials are not configured")
        alert_client = self._local_alert_client
        if alert_client is None:
            raise LocalAlertAuthenticationError("RVM3 local alert session is not configured")
        try:
            login_page = await alert_client.get("/wp-login.php")
            login_page.raise_for_status()
            alert_path = f"{self.system_path}/alert-settings/"
            response = await alert_client.post(
                "/wp-login.php",
                data={
                    "log": self.local_username,
                    "pwd": self.local_password,
                    "wp-submit": "Log In",
                    "redirect_to": f"{self.base_url}{alert_path}",
                    "testcookie": "1",
                },
            )
            response.raise_for_status()
            if not self._is_login_response(response) and not self._has_alert_view(response.text):
                response = await alert_client.get(alert_path)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LocalAlertAuthenticationError("RVM3 local alert authentication failed") from exc
        if self._is_login_response(response) or not self._has_alert_view(response.text):
            raise LocalAlertAuthenticationError("RVM3 local alert authentication failed")
        return response.text

    async def acknowledge_alert(self, fingerprint: str) -> AlertAcknowledgementResult:
        """Acknowledge exactly one current local alert and verify the result.

        The lock plus authoritative reread makes sequential and concurrent
        duplicate requests idempotent: only the first unacknowledged instance
        can reach the vendor write endpoint.
        """
        if self.access_mode != "local" or not self.has_local_alert_credentials:
            raise AlertAcknowledgementError("Local authenticated alert access is required")
        alert_client = self._local_alert_client
        if alert_client is None:
            raise AlertAcknowledgementError("Local alert session is not configured")

        async with self._alert_action_lock:
            try:
                context = parse_alert_action_context(await self.fetch_alert_settings())
            except (AlertParseError, RVWhisperError, httpx.HTTPError) as exc:
                raise AlertAcknowledgementError(
                    "Current RV Whisper acknowledgement controls are unavailable"
                ) from exc
            matches = [alert for alert in context.alerts if alert.fingerprint == fingerprint]
            if len(matches) != 1:
                raise AlertAcknowledgementStale("Alert is no longer one current RV Whisper instance")
            current = matches[0]
            if current.acknowledged:
                return AlertAcknowledgementResult("already_acknowledged", current, context.alerts)
            if not current.vendor_id:
                raise AlertAcknowledgementError("RV Whisper did not expose an acknowledgement control for this alert")

            try:
                response = await alert_client.post(
                    f"{self.system_path}/wp-admin/admin-ajax.php",
                    data={
                        "action": "acknowledge_alert",
                        "user_id": context.user_id,
                        "alert_id": current.vendor_id,
                        "bt_nonce": context.nonce,
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                return await self._resolve_ambiguous_acknowledgement(fingerprint, exc)
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise AlertAcknowledgementError("RV Whisper rejected the acknowledgement request")

            return await self._verify_acknowledgement(fingerprint)

    async def _verify_acknowledgement(
        self,
        fingerprint: str,
    ) -> AlertAcknowledgementResult:
        try:
            alerts = parse_active_alerts(await self.fetch_alert_settings())
        except (RVWhisperError, AlertParseError, httpx.HTTPError) as exc:
            raise AlertAcknowledgementUncertain(
                "Acknowledgement was sent once but RV Whisper confirmation is unavailable"
            ) from exc
        matches = [alert for alert in alerts if alert.fingerprint == fingerprint]
        if len(matches) == 1 and matches[0].acknowledged:
            return AlertAcknowledgementResult("confirmed", matches[0], alerts)
        raise AlertAcknowledgementUncertain(
            "Acknowledgement was sent once but RV Whisper did not confirm it"
        )

    async def _resolve_ambiguous_acknowledgement(
        self,
        fingerprint: str,
        cause: Exception,
    ) -> AlertAcknowledgementResult:
        try:
            return await self._verify_acknowledgement(fingerprint)
        except AlertAcknowledgementUncertain as exc:
            raise AlertAcknowledgementUncertain(
                "Acknowledgement result is uncertain; the request was not retried"
            ) from cause

    async def fetch_sensor_page(self, sensor: Sensor) -> str:
        """Return a sensor detail page for its read-only alert summary."""
        response = await self._client.get(f"{self.system_path}/sensor", params={"sensor_id": sensor.id})
        response.raise_for_status()
        return response.text

    @staticmethod
    def _extract(text: str, pattern: str, label: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            raise RVWhisperError(f"Could not find {label}; the RV Whisper page may have changed")
        return match.group(1)


def client_from_environment(environment: Mapping[str, str] | None = None) -> RVWhisperClient:
    """Build a client from the protected dashboard environment.

    Local mode deliberately does not require gateway credentials. The base URL
    and optional system path are administrator-controlled installation values.
    """
    values = os.environ if environment is None else environment
    access_mode = values.get("RVW_ACCESS_MODE", "gateway").strip().lower()
    rvm_id = values.get("RVW_ID", "").strip()
    if access_mode == "gateway" and not rvm_id:
        raise ValueError("Gateway access requires RVW_ID")
    base_url = values.get("RVW_BASE_URL", "").strip() or None
    configured_path = values.get("RVW_SYSTEM_PATH")
    system_path = configured_path if configured_path and configured_path.strip() else None
    if access_mode == "local" and not base_url:
        raise ValueError("Local access requires RVW_BASE_URL with the RVM3 LAN address")
    return RVWhisperClient(
        rvm_id or "local-rvm",
        values.get("RVW_USERNAME", "").strip(),
        values.get("RVW_PASSWORD", ""),
        access_mode=access_mode,
        base_url=base_url,
        system_path=system_path,
        local_username=values.get("RVW_LOCAL_USERNAME", "").strip(),
        local_password=values.get("RVW_LOCAL_PASSWORD", ""),
    )
