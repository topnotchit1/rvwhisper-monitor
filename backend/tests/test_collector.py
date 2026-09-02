import httpx

from rv_dashboard.collector import describe_collector_failure, next_failure_backoff


def test_collector_failures_are_nonempty_and_do_not_expose_urls():
    request = httpx.Request("GET", "http://10.0.0.20/private")
    failures = [
        describe_collector_failure(httpx.ConnectTimeout("", request=request)),
        describe_collector_failure(httpx.ReadTimeout("", request=request)),
        describe_collector_failure(httpx.ConnectError("device-user", request=request)),
    ]

    assert [failure["code"] for failure in failures] == ["connect_timeout", "read_timeout", "unreachable"]
    assert all(failure["message"] for failure in failures)
    assert all("10.0.0.20" not in failure["message"] for failure in failures)
    assert all("device-user" not in failure["message"] for failure in failures)


def test_local_retry_is_prompt_while_gateway_backoff_remains_conservative():
    assert next_failure_backoff("local", 60, 600) == 60
    assert next_failure_backoff("local", 30, 600) == 30
    assert next_failure_backoff("gateway", 60, 60) == 120
    assert next_failure_backoff("gateway", 60, 600) == 900
