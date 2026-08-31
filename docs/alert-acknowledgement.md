# Dashboard alert acknowledgement design

## Status

Not enabled. Read-only inspection of RVM3 firmware 4.831 confirmed the request shape, and deliberately triggered noncritical alerts have now validated read-only alert detection. Authenticated acknowledgement success and failure behavior must still be validated before the dashboard can send acknowledgements.

The local RVM3 login is a device-local WordPress account, separate from the RV Whisper cloud account. Any future acknowledgement integration must use installation-specific local credentials stored only in the protected Pi environment; credentials, cookies, and nonces must never be sent to the browser or committed.

## Current read-only behavior

- The collector prefers the consolidated active-alert view when the current session can read it.
- If that page requires a local device login, local mode reads each public sensor page and imports the titles shown under **Current Alerts**.
- Public sensor pages do not expose acknowledgement or creation metadata. The dashboard therefore treats those alerts as unacknowledged/needs-attention rather than risking a false all-clear.
- A missing, changed, or partially unavailable vendor page is a recoverable collection failure and does not clear the last successfully observed active-alert set.
- This fallback never submits a form, acknowledges an alert, changes a trigger, or affects RV Whisper notification delivery.

## Confirmed vendor request shape

- `POST /wp-admin/admin-ajax.php` on the local RVM3.
- Form fields: `action=acknowledge_alert`, the current local `user_id`, the active vendor `alert_id`, and the page's `bt_nonce`.
- The vendor alert identifier comes from the acknowledgement button's `data-alertid` attribute.
- The response is JSON with `success` and `message`; the vendor UI hides the button only after `success` is true.
- Active noncritical alerts were observed through the read-only sensor view. The authenticated vendor identifier and acknowledgement response have not yet been exercised, so no acknowledgement was sent.

## Safety boundary

RV Whisper continues to evaluate conditions, create alert instances, send email and text notifications, decide when conditions clear, and retain authoritative history. The dashboard may eventually request acknowledgement of one current alert instance; failure of the Pi or this action must never interrupt RV Whisper alerting.

Acknowledgement is not dismissal. It stops repeat RV Whisper notifications for the current active alert instance while the triggering condition remains visible. A later recurrence is a new alert instance.

## Required behavior

- Disabled by default with `ALLOW_ALERT_ACK=false`.
- Available only to an authenticated local operator and only for a currently active, unacknowledged alert.
- No bulk acknowledgement and no dashboard controls for editing, disabling, or deleting alert triggers.
- A confirmation explains that repeat notifications will stop but the condition will remain active.
- The browser sends only the dashboard's opaque alert identifier; vendor cookies, credentials, nonces, and form fields remain in the backend.
- The backend refreshes the alert page, validates exactly one matching current alert, submits the vendor action once, and re-reads the page.
- The UI shows success only after RV Whisper reports the alert as acknowledged.
- Timeout or ambiguous results remain unconfirmed, trigger a fresh read, and are never reported as success optimistically.
- Requested, confirmed, failed, and uncertain results are written to the local event log without contact information.
- A failed acknowledgement command does not change collector health or stop telemetry polling.

## Validation required before implementation

Using a deliberately triggered, noncritical test alert, privately validate:

1. the exact authenticated unacknowledged-alert markup and vendor identifier;
2. the response and page state after a successful acknowledgement;
3. behavior for a repeated request, a stale alert, and an interrupted request;
4. whether the local device account password can be changed on supported firmware.

Raw HTML and credentials remain private installation artifacts and are never committed.
