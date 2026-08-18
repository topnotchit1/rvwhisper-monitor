# Minnie Winnie Unified RV Dashboard

A clean, wall-mounted systems dashboard for a 2025 Winnebago Minnie Winnie 31K.

> **Normal = quiet. Problem = obvious. Detail = available when requested.**

The dashboard is a visualization and diagnostic interface. **RV Whisper remains the authoritative, independent monitoring, history, and alerting system.** A Pi failure must never prevent RV Whisper from notifying the owner.

## What is implemented

- Responsive, kiosk-friendly Home, Power, Climate, Tanks, and Events views
- Deliberate Normal, Shore Power Lost, and Stale Data preview states
- Diagnostic shore-loss summary showing battery load, dog temperature, and connectivity
- Conservative energy flow that never invents source attribution from net shunt current
- Normalized readings such as `power.battery.soc` and `environment.dog.temperature`
- RV Whisper collector based on the public `Yeraze/rvwhisper-monitor` authentication and sensor-discovery flow
- Automatic session recovery, bounded polling, internal event bus, SSE browser updates, and SQLite history
- Demo mode that runs without RV hardware; live mode requires explicit credentials and an observed sensor map

## Architecture

```text
BTH1 / Hughes / SeeLeveL ─► RV Whisper RVM3 ─► RV Whisper service
                                                        │ 30–60 sec
                                                        ▼
PowerMon direct BLE (phase 2) ───────────────► Local collector
                                                        │
                                             normalized state + SQLite
                                                        │ SSE
                                                        ▼
                                             touchscreen web dashboard
```

External acquisition may poll conservatively. Everything after collection is change-driven. The browser never polls individual sensors.

## Run the dashboard UI

Requires Node.js 22 or later.

```bash
npm ci
npm run dev
```

Open `http://localhost:3000`. Without the local API, the UI clearly labels itself **Demo** and uses representative data.

## Run the local API

Requires Python 3.11 or later.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
rv-dashboard
```

The API listens on `http://localhost:8080` by default. Set `NEXT_PUBLIC_DASHBOARD_API_URL` for a different host.

### Live RV Whisper mode

1. Operate in demo mode first.
2. Capture real JSON for each installed sensor.
3. Copy `backend/config/sensor-map.example.json` to `sensor-map.json` and map only observed fields.
4. Set `DASHBOARD_MODE=live` plus `RVW_ID`, `RVW_USERNAME`, and `RVW_PASSWORD`.
5. Start with `RVW_POLL_SECONDS=60`; do not reduce it until RV Whisper confirms an acceptable cadence.

Credentials belong in the Pi's protected environment file and must never be committed.

## Safety and data freshness

- RV Whisper alerts remain enabled and independent.
- Every reading includes its observation time, source, and health.
- Values older than the configured freshness window become **STALE**.
- A collector or internet failure never silently presents old data as current.
- Source-specific data is mapped at the adapter boundary, not inside UI components.

## Project map

- `app/` — touchscreen interface
- `backend/rv_dashboard/` — collector, normalizer, SQLite store, event bus, and API
- `backend/config/` — sensor mapping populated only after payload capture
- `backend/tests/` — freshness, normalization, and storage tests
- `docs/architecture.md` — system decisions and failure boundaries
- `docs/privacy.md` — public-repository privacy rules
- `docs/open-questions/` — GitHub-ready issue drafts
- `deploy/` — Raspberry Pi service examples

## Public repository safety

Runtime databases, credentials, real sensor maps, payload captures, bytecode, and local environment files are excluded from Git. `npm run privacy:scan` checks source files for email addresses, home-directory paths, device IDs, and populated credential assignments. CI runs the same check before building the dashboard.

## Reference

Data-access behavior is derived from [Yeraze/rvwhisper-monitor](https://github.com/Yeraze/rvwhisper-monitor), used as a reference rather than a UI base. That project documents the current web-service flow: login CSRF fields, authenticated cookies, dashboard nonce and sensor discovery, and `get_latest_data_by_date` payload retrieval.

## Status

The software foundation and hardware-independent MVP are ready. Live sensor mapping is intentionally pending actual RVM3, Hughes, PowerMon, and SeeLeveL payloads. See the open-question drafts before making hardware-specific assumptions.
