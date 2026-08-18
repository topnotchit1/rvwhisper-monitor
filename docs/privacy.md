# Privacy and repository hygiene

This repository is designed to remain safe for public hosting.

## Never commit

- `.env` files or RV Whisper credentials
- RVM identifiers, sensor serial numbers, MAC addresses, or Bluetooth addresses
- Raw RV Whisper payload captures before redaction
- `backend/config/sensor-map.json` when it contains real sensor or room names
- SQLite runtime databases or exported history
- Home addresses, precise RV locations, Wi-Fi names, IP addresses, or access URLs
- Screenshots containing account names, device IDs, notifications, or location data

The ignore rules exclude these runtime and site-specific files. Only sanitized examples belong in the repository.

## Before publishing a fixture

Replace account and device identifiers with stable fictional values, generalize sensor names, remove coordinates and network data, and verify that timestamps do not disclose travel or occupancy patterns. Run the repository privacy scan described in the release checklist before every public release.

## Commit identity

Use either a project identity or GitHub's privacy-preserving `noreply` address. Do not configure a personal email in this repository unless intentionally desired.
