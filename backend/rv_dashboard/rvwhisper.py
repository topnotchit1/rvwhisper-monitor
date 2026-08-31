from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx


class RVWhisperError(RuntimeError):
    pass


@dataclass(frozen=True)
class Sensor:
    id: str
    name: str


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
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if access_mode not in {"gateway", "local"}:
            raise ValueError("RVW_ACCESS_MODE must be 'gateway' or 'local'")
        if access_mode == "gateway" and (not username or not password):
            raise ValueError("Gateway access requires RVW_USERNAME and RVW_PASSWORD")
        self.rvm_id = rvm_id
        self.username = username
        self.password = password
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
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    async def close(self) -> None:
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
        response = await self._client.get(f"{self.system_path}/alert-settings/")
        if response.status_code in {401, 403} and retry_auth and self.access_mode == "gateway":
            await self.authenticate()
            return await self.fetch_alert_settings(retry_auth=False)
        if response.status_code in {401, 403}:
            raise RVWhisperError("RV Whisper rejected the refreshed alert session")
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
    )
