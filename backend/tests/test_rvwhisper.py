from urllib.parse import parse_qs

import httpx
import pytest

from rv_dashboard.rvwhisper import RVWhisperClient, client_from_environment


@pytest.mark.asyncio
async def test_local_mode_skips_login_and_uses_root_ajax_endpoint():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(
                200,
                text='<a href="sensor?sensor_id=42" title="Power Watchdog">Power</a>',
            )
        if request.method == "POST" and request.url.path == "/wp-admin/admin-ajax.php":
            return httpx.Response(200, json={"data": [{"Volts": 121}]})
        return httpx.Response(404)

    client = RVWhisperClient(
        "sample-rvm",
        access_mode="local",
        base_url="http://rvm.local",
        transport=httpx.MockTransport(handler),
    )
    try:
        sensors = await client.authenticate()
        payload = await client.fetch_sensor(sensors[0])
    finally:
        await client.close()

    assert [(sensor.id, sensor.name) for sensor in sensors] == [("42", "Power Watchdog")]
    assert payload == {"data": [{"Volts": 121}]}
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/"),
        ("POST", "/wp-admin/admin-ajax.php"),
    ]
    form = parse_qs(requests[1].content.decode(), keep_blank_values=True)
    assert form["sensor"] == ["42"]
    assert form["bt_nonce"] == [""]


@pytest.mark.asyncio
async def test_gateway_mode_retains_login_csrf_and_system_prefix():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, text='<input name="csrf_value" value="value"><input name="csrf_name" value="name">')
        if request.method == "POST" and request.url.path == "/account/login":
            return httpx.Response(200)
        if request.method == "GET" and request.url.path == "/sample-rvm":
            return httpx.Response(200, text='"ajax_nonce":"nonce-1" <a href="sensor?sensor_id=7" title="Temperature">Temp</a>')
        return httpx.Response(404)

    client = RVWhisperClient(
        "sample-rvm",
        "user",
        "password",
        transport=httpx.MockTransport(handler),
    )
    try:
        sensors = await client.authenticate()
    finally:
        await client.close()

    assert sensors[0].id == "7"
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/"),
        ("POST", "/account/login"),
        ("GET", "/sample-rvm"),
    ]


def test_environment_factory_requires_only_local_address_in_local_mode():
    client = client_from_environment({
        "RVW_ACCESS_MODE": "local",
        "RVW_BASE_URL": "http://rvm.local",
        "RVW_SYSTEM_PATH": "",
    })
    assert client.access_mode == "local"
    assert client.system_path == ""


def test_environment_factory_requires_gateway_credentials():
    with pytest.raises(ValueError, match="Gateway access requires"):
        client_from_environment({"RVW_ID": "sample-rvm"})


def test_base_url_rejects_embedded_paths():
    with pytest.raises(ValueError, match="must not include a path"):
        RVWhisperClient("sample-rvm", access_mode="local", base_url="http://rvm.local/private")
