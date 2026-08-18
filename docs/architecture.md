# Architecture decisions

## Safety boundary

The custom application is not an alarm system. RV Whisper independently owns alert thresholds, notification delivery, and long-term authoritative history. The Pi may mirror conditions visually, but no alert path passes through the Pi.

## Data flow

1. The RV Whisper adapter authenticates to the web service and discovers sensors.
2. A configurable collector polls no faster than 30 seconds; 60 seconds is the default.
3. A rule-based normalizer translates observed vendor fields to stable paths.
4. Changed readings update the current snapshot, append to SQLite, and publish to the event bus.
5. Server-Sent Events push one coherent snapshot to all connected browsers.
6. The UI computes freshness from the observation timestamp and displays stale state explicitly.

## Normalized model

The path is the API contract. Each reading also carries `value`, `unit`, `observed_at`, `age_seconds`, `source`, and `health`.

```text
power.battery.{soc,voltage,current,power}
power.ac.{connected,voltage,current,power,frequency}
environment.{dog,coach,fridge,freezer}.temperature
tank.{fresh,gray,black,propane}.percent
network.{internet,rvwhisper}.online
```

Unknown fields are not guessed. Sensor rules live in `sensor-map.json` and are added only after a real payload is archived and reviewed.

## Storage

SQLite stores one current row per normalized path, 24–72 hours of high-resolution samples, and significant diagnostic events. The indexes match the actual queries: recent samples for one path and events by recency. RV Whisper remains the long-term history.

## Failure behavior

- Authentication expiry: reauthenticate and rediscover sensors.
- Invalid or changed HTML/JSON: record collector failure; retain old values only as stale context.
- Internet outage: exponential retry up to 15 minutes; no rapid hammering.
- Browser disconnect: EventSource reconnects; one state snapshot is sent immediately.
- Pi failure: RV Whisper alerts continue without the Pi.
- Direct PowerMon failure in phase 2: fall back to RV Whisper data; never merge incompatible timestamps as current.

## PowerMon phase 2

Direct BLE must remain optional until simultaneous RVM3 and Pi consumers are proven reliable. A direct adapter publishes to the same normalized paths with explicit source and timestamp; the UI does not know which adapter supplied the reading.
