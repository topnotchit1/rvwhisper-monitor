from urllib.parse import parse_qs

import httpx
import pytest

from rv_dashboard.rvwhisper import LocalAlertAuthenticationError, RVWhisperClient, client_from_environment


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
        if request.method == "GET" and request.url.path == "/sensor":
            return httpx.Response(200, text="<h3>Current Alerts</h3><div>No Alerts!</div>")
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
        sensor_page = await client.fetch_sensor_page(sensors[0])
    finally:
        await client.close()

    assert [(sensor.id, sensor.name) for sensor in sensors] == [("42", "Power Watchdog")]
    assert payload == {"data": [{"Volts": 121}]}
    assert "Current Alerts" in sensor_page
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/"),
        ("POST", "/wp-admin/admin-ajax.php"),
        ("GET", "/sensor"),
    ]
    form = parse_qs(requests[1].content.decode(), keep_blank_values=True)
    assert form["sensor"] == ["42"]
    assert form["bt_nonce"] == [""]
    assert requests[2].url.params["sensor_id"] == "42"


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


@pytest.mark.asyncio
async def test_local_alert_authentication_uses_separate_device_credentials():
    requests: list[httpx.Request] = []
    acknowledged_html = """
    <div id="view-alerts"><ul>
      <li class="row acknowledged-alert"><h3>Alert: Test - ACKNOWLEDGED</h3></li>
    </ul></div>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/alert-settings/":
            if "wordpress_logged_in_test" in request.headers.get("cookie", ""):
                return httpx.Response(200, text=acknowledged_html)
            return httpx.Response(200, text='<form id="loginform"><input name="log"><input name="pwd"></form>')
        if request.method == "GET" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"></form>', headers={"set-cookie": "wordpress_test_cookie=1"})
        if request.method == "POST" and request.url.path == "/wp-login.php":
            return httpx.Response(
                302,
                headers={
                    "location": "/alert-settings/",
                    "set-cookie": "wordpress_logged_in_test=session",
                },
            )
        return httpx.Response(404)

    client = RVWhisperClient(
        "sample-rvm",
        "cloud-user",
        "cloud-password",
        access_mode="local",
        base_url="http://rvm.local",
        local_username="device-user",
        local_password="device-password",
        transport=httpx.MockTransport(handler),
    )
    try:
        html = await client.fetch_alert_settings()
    finally:
        await client.close()

    assert "ACKNOWLEDGED" in html
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/alert-settings/"),
        ("GET", "/wp-login.php"),
        ("POST", "/wp-login.php"),
        ("GET", "/alert-settings/"),
    ]
    form = parse_qs(requests[2].content.decode(), keep_blank_values=True)
    assert form["log"] == ["device-user"]
    assert form["pwd"] == ["device-password"]
    assert "cloud-user" not in requests[2].content.decode()
    assert "cloud-password" not in requests[2].content.decode()


@pytest.mark.asyncio
async def test_local_alert_authentication_handles_logged_out_placeholder_page():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/alert-settings/":
            if "wordpress_logged_in_test" in request.headers.get("cookie", ""):
                return httpx.Response(200, text='<div id="view-alerts"></div>')
            return httpx.Response(200, text="<html><main>Sign in to view alerts</main></html>")
        if request.method == "GET" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"></form>')
        if request.method == "POST" and request.url.path == "/wp-login.php":
            return httpx.Response(
                302,
                headers={
                    "location": "/alert-settings/",
                    "set-cookie": "wordpress_logged_in_test=session",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = RVWhisperClient(
        "sample-rvm",
        access_mode="local",
        base_url="http://rvm.local",
        local_username="device-user",
        local_password="device-password",
        transport=httpx.MockTransport(handler),
    )
    try:
        html = await client.fetch_alert_settings()
    finally:
        await client.close()

    assert 'id="view-alerts"' in html
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/alert-settings/"),
        ("GET", "/wp-login.php"),
        ("POST", "/wp-login.php"),
        ("GET", "/alert-settings/"),
    ]


@pytest.mark.asyncio
async def test_local_alert_authentication_fetches_alerts_when_device_ignores_redirect():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        logged_in = "wordpress_logged_in_test" in request.headers.get("cookie", "")
        if request.method == "GET" and request.url.path == "/alert-settings/":
            if logged_in:
                return httpx.Response(200, text='<div id="view-alerts"></div>')
            return httpx.Response(200, text="<html><main>Sign in to view alerts</main></html>")
        if request.method == "GET" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"></form>')
        if request.method == "POST" and request.url.path == "/wp-login.php":
            return httpx.Response(
                302,
                headers={"location": "/", "set-cookie": "wordpress_logged_in_test=session"},
            )
        if request.method == "GET" and request.url.path == "/" and logged_in:
            return httpx.Response(200, text="<html><main>Dashboard</main></html>")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = RVWhisperClient(
        "sample-rvm",
        access_mode="local",
        base_url="http://rvm.local",
        local_username="device-user",
        local_password="device-password",
        transport=httpx.MockTransport(handler),
    )
    try:
        html = await client.fetch_alert_settings()
    finally:
        await client.close()

    assert 'id="view-alerts"' in html
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/alert-settings/"),
        ("GET", "/wp-login.php"),
        ("POST", "/wp-login.php"),
        ("GET", "/"),
        ("GET", "/alert-settings/"),
    ]


@pytest.mark.asyncio
async def test_local_alert_authentication_does_not_leak_cookies_into_telemetry_session():
    telemetry_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal telemetry_request
        logged_in = "wordpress_logged_in_test" in request.headers.get("cookie", "")
        if request.method == "GET" and request.url.path == "/":
            if logged_in:
                return httpx.Response(200, text="<html><main>Dashboard</main></html>")
            return httpx.Response(
                200,
                text='"ajax_nonce":"nonce-1" sensor?sensor_id=7" title="Battery"',
            )
        if request.method == "GET" and request.url.path == "/alert-settings/":
            if logged_in:
                return httpx.Response(200, text='<div id="view-alerts"></div>')
            return httpx.Response(200, text="<html><main>Sign in to view alerts</main></html>")
        if request.method == "GET" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"></form>')
        if request.method == "POST" and request.url.path == "/wp-login.php":
            return httpx.Response(
                302,
                headers={"location": "/", "set-cookie": "wordpress_logged_in_test=session"},
            )
        if request.method == "POST" and request.url.path == "/wp-admin/admin-ajax.php":
            telemetry_request = request
            return httpx.Response(200, json={})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = RVWhisperClient(
        "sample-rvm",
        access_mode="local",
        base_url="http://rvm.local",
        local_username="device-user",
        local_password="device-password",
        transport=httpx.MockTransport(handler),
    )
    try:
        sensors = await client.authenticate()
        await client.fetch_alert_settings()
        await client.fetch_sensor(sensors[0])
    finally:
        await client.close()

    assert telemetry_request is not None
    assert "wordpress_logged_in" not in telemetry_request.headers.get("cookie", "")


@pytest.mark.asyncio
async def test_rejected_local_alert_credentials_raise_sanitized_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/alert-settings/":
            return httpx.Response(200, text='<form id="loginform"><input name="log"><input name="pwd"></form>')
        if request.method == "GET" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"></form>')
        if request.method == "POST" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"><div>invalid</div></form>')
        return httpx.Response(404)

    client = RVWhisperClient(
        "sample-rvm",
        access_mode="local",
        base_url="http://rvm.local",
        local_username="device-user",
        local_password="device-password",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(LocalAlertAuthenticationError) as error:
            await client.fetch_alert_settings()
    finally:
        await client.close()

    assert str(error.value) == "RVM3 local alert authentication failed"
    assert "device-user" not in str(error.value)
    assert "device-password" not in str(error.value)


@pytest.mark.asyncio
async def test_local_alert_authentication_refreshes_after_forbidden_response():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/alert-settings/":
            if "wordpress_logged_in_test" in request.headers.get("cookie", ""):
                return httpx.Response(200, text='<div id="view-alerts"></div>')
            return httpx.Response(403)
        if request.method == "GET" and request.url.path == "/wp-login.php":
            return httpx.Response(200, text='<form id="loginform"></form>')
        if request.method == "POST" and request.url.path == "/wp-login.php":
            return httpx.Response(
                302,
                headers={
                    "location": "/alert-settings/",
                    "set-cookie": "wordpress_logged_in_test=session",
                },
            )
        return httpx.Response(404)

    client = RVWhisperClient(
        "sample-rvm",
        access_mode="local",
        base_url="http://rvm.local",
        local_username="device-user",
        local_password="device-password",
        transport=httpx.MockTransport(handler),
    )
    try:
        html = await client.fetch_alert_settings()
    finally:
        await client.close()

    assert 'id="view-alerts"' in html
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/alert-settings/"),
        ("GET", "/wp-login.php"),
        ("POST", "/wp-login.php"),
        ("GET", "/alert-settings/"),
    ]


def test_environment_factory_requires_only_local_address_in_local_mode():
    client = client_from_environment({
        "RVW_ACCESS_MODE": "local",
        "RVW_BASE_URL": "http://rvm.local",
        "RVW_SYSTEM_PATH": "",
    })
    assert client.access_mode == "local"
    assert client.system_path == ""


def test_environment_factory_keeps_local_and_gateway_credentials_separate():
    client = client_from_environment({
        "RVW_ACCESS_MODE": "local",
        "RVW_BASE_URL": "http://rvm.local",
        "RVW_USERNAME": "cloud-user",
        "RVW_PASSWORD": "cloud-password",
        "RVW_LOCAL_USERNAME": "device-user",
        "RVW_LOCAL_PASSWORD": "device-password",
    })
    assert client.local_username == "device-user"
    assert client.local_password == "device-password"
    assert client.has_local_alert_credentials is True


def test_local_alert_credentials_must_be_a_complete_pair():
    with pytest.raises(ValueError, match="both RVW_LOCAL_USERNAME and RVW_LOCAL_PASSWORD"):
        client_from_environment({
            "RVW_ACCESS_MODE": "local",
            "RVW_BASE_URL": "http://rvm.local",
            "RVW_LOCAL_USERNAME": "device-user",
        })


def test_environment_factory_requires_gateway_credentials():
    with pytest.raises(ValueError, match="Gateway access requires"):
        client_from_environment({"RVW_ID": "sample-rvm"})


def test_base_url_rejects_embedded_paths():
    with pytest.raises(ValueError, match="must not include a path"):
        RVWhisperClient("sample-rvm", access_mode="local", base_url="http://rvm.local/private")
