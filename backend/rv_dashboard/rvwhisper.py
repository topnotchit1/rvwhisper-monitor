from __future__ import annotations

import re
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

    BASE_URL = "https://access.rvwhisper.com"

    def __init__(self, rvm_id: str, username: str, password: str, timeout_seconds: float = 20):
        self.rvm_id = rvm_id
        self.username = username
        self.password = password
        self._nonce: str | None = None
        self._client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=timeout_seconds, follow_redirects=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def authenticate(self) -> list[Sensor]:
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
        dashboard = await self._client.get(f"/{self.rvm_id}")
        dashboard.raise_for_status()
        self._nonce = self._extract(dashboard.text, r'"ajax_nonce":"([\w-]+)"', "ajax_nonce")
        matches = re.finditer(r'sensor\?sensor_id=(\d+)"\s+title="([^\"]+)"', dashboard.text)
        sensors = [Sensor(match.group(1), match.group(2).strip()) for match in matches]
        if not sensors:
            raise RVWhisperError("No sensors were discovered in the RV Whisper dashboard")
        return sensors

    async def fetch_sensor(self, sensor: Sensor, interval_hours: int = 1, retry_auth: bool = True) -> dict[str, Any]:
        if self._nonce is None:
            await self.authenticate()
        response = await self._client.post(f"/{self.rvm_id}/wp-admin/admin-ajax.php", data={
            "action": "get_latest_data_by_date",
            "sensor": sensor.id,
            "date_interval": str(interval_hours),
            "browser_gmt_offset": "0",
            "charting": "false",
            "bt_nonce": self._nonce or "",
        })
        if response.status_code in {401, 403} and retry_auth:
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

    @staticmethod
    def _extract(text: str, pattern: str, label: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            raise RVWhisperError(f"Could not find {label}; the RV Whisper page may have changed")
        return match.group(1)
