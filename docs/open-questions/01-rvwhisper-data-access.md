# RV Whisper data access and payload capture

## Questions

- Capture exact JSON for BTH1, BV2, Hughes PWD30EPOHW, PowerMon-5S, and SeeLeveL 709-BTP7.
- Confirm a responsible continuously running polling cadence with RV Whisper.
- Ask whether an official local RVM3 REST, JSON, WebSocket, or MQTT endpoint exists.
- Measure login/session lifetime, nonce renewal, cookie expiry, and recovery after internet loss.
- Track cloud-side notification when an RVM3 stops checking in.

## Done when

Redacted payload fixtures and field maps are committed, the approved cadence is documented, and authentication recovery tests pass.

## Guardrail

Do not hard-code unobserved fields or scrape more frequently than the agreed cadence.
