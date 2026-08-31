from rv_dashboard.alerts import parse_active_alerts, parse_sensor_active_alerts


def test_parser_returns_acknowledged_and_unacknowledged_active_alerts():
    html = """
    <div id="view-alerts">
      <ul>
        <li class="row"><h3>Alert: Freezer is warm</h3><h4><strong>Created:</strong><br>August 20, 2026 8:00pm by <strong>admin</strong></h4></li>
        <li class="row acknowledged-alert"><h3>Alert: Refrigerator temperature high <span>- ACKNOWLEDGED</span></h3><h4><strong>Created:</strong><br>August 20, 2026 6:47pm by <strong>admin</strong></h4><h4>Acknowleged by: Owner</h4></li>
      </ul>
    </div>
    """
    alerts = parse_active_alerts(html)
    assert [(alert.title, alert.acknowledged) for alert in alerts] == [
        ("Freezer is warm", False),
        ("Refrigerator temperature high", True),
    ]
    assert alerts[0].created_at == "2026-08-20T20:00:00"


def test_parser_rejects_login_or_changed_pages():
    try:
        parse_active_alerts("<html><form id='login'></form></html>")
    except ValueError as exc:
        assert "alert list" in str(exc)
    else:
        raise AssertionError("missing alert list must not clear active alerts")


def test_sensor_page_parser_returns_public_active_alerts_conservatively():
    html = """
    <main>
      <h3>History</h3>
      <div><h4>Last Updated: Aug 31, 2026 2:57pm</h4></div>
      <div class="col-xs-12">
        <h3 class="clearfix"><a name="alerts"><span>Current Alerts</span></a></h3>
        <div><h4><span class="glyphicon glyphicon-alert"></span>Alert: Refrigerator temperature high</h4></div>
      </div>
    </main>
    """
    alerts = parse_sensor_active_alerts(html, "541")
    assert [(alert.title, alert.acknowledged, alert.created_at) for alert in alerts] == [
        ("Refrigerator temperature high", False, None),
    ]


def test_sensor_page_parser_allows_no_current_alerts():
    html = "<h3>Current Alerts</h3><div>No Alerts!</div>"
    assert parse_sensor_active_alerts(html, "545") == []
