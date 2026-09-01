# Raspberry Pi installation and live-data checklist

This guide prepares a Raspberry Pi as the local collector, history store, web server, and touchscreen kiosk. RV Whisper remains the independent alerting authority.

## Hardware and operating-system choice

- Prefer Raspberry Pi OS 64-bit with Desktop so Chromium and the current `labwc` kiosk flow are available.
- A Pi with at least 1 GB RAM is the reliable kiosk target. [Raspberry Pi's current kiosk guidance](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/) recommends a Pi 3 or newer with at least 1 GB RAM.
- A Pi Zero 2 W has only 512 MB. The installer permits it but prints a warning; treat it as an experiment and keep a Pi 4 with 2 GB or more as the fallback if Chromium or on-device builds are unstable.
- Use a quality power supply, a high-endurance microSD card, cooling appropriate to the enclosure, and a 1024×600 capacitive display.

In Raspberry Pi Imager, preconfigure a unique username and password, Wi-Fi, time zone, hostname, and SSH. Do not reuse a default password.

## Before running the installer

Install Node.js 22 or later for Linux ARM64 from the [official Node.js distribution](https://nodejs.org/en/download), then confirm:

```bash
node --version
npm --version
python3 --version
```

Clone this repository on the Pi and run the installer from the checkout:

```bash
git clone https://github.com/<your-account>/rvwhisper-monitor.git
cd rvwhisper-monitor
sudo bash deploy/install-pi.sh
```

The installer creates a dedicated `rvdashboard` service account, a versioned release under `/opt/minnie-dashboard`, protected configuration under `/etc/minnie-dashboard`, persistent data under `/var/lib/minnie-dashboard`, and two systemd services. Existing credentials and sensor mappings are preserved during later installs.

When run interactively, the installer offers a guided configuration wizard. It configures the RV display identity, demo/direct-LAN/gateway access, section visibility and labels, climate and tank item counts, normalized display paths, and which readings appear on Home. All answers are staged and validated before either protected file is replaced, so canceling the wizard leaves the existing installation unchanged. These values are installation-specific and are never written into the Git checkout. Run the configuration step again at any time with:

```bash
sudo /opt/minnie-dashboard/current/deploy/configure-dashboard.sh
```

The wizard does not change `sensor-map.json`; vendor field mapping stays a separate, evidence-based step after private payload capture. It also never asks for Wi-Fi credentials. Gateway passwords, when used, are entered without echo and remain only in the root-owned environment file. In local mode it can optionally store a separate device-local account for read-only acknowledged-alert status. Cloud credentials are never reused for that login.

Local RVM3 firmware may serve authenticated pages over plain HTTP. Configure device-local alert credentials only on the trusted RV LAN, use a unique password when possible, and change any vendor factory password if the installed firmware supports it. Anonymous local telemetry remains available when these optional credentials are omitted or rejected.

Validate the current profile and environment file without changing them:

```bash
sudo /opt/minnie-dashboard/current/backend/.venv/bin/rv-dashboard-configure --check
```

## Verify demo mode first

```bash
sudo /opt/minnie-dashboard/current/deploy/verify-pi.sh
systemctl status minnie-dashboard-api minnie-dashboard-ui
```

Open `http://localhost:3000` on the Pi. From another device on the same trusted network, use `http://<pi-hostname>.local:3000`.

Do not continue until the Home screen says **Demo**, all navigation works, and the verification command has no failures.

## Enable touchscreen kiosk mode

Run this as the desktop user, without `sudo`:

```bash
/opt/minnie-dashboard/current/deploy/install-kiosk.sh
sudo raspi-config
```

In `raspi-config`, select desktop boot with automatic login only if physical access to the display is controlled. Configure display blanking to match how the RV is used, then reboot. The kiosk entry follows Raspberry Pi's current Chromium and `labwc` autostart guidance.

## Capture real RV Whisper payloads privately

First verify that every installed sensor appears correctly in the official RV Whisper interface. Then edit the Pi-only environment file:

```bash
sudoedit /etc/minnie-dashboard/dashboard.env
```

Leave `DASHBOARD_MODE=demo` while configuring access. When the Pi and RVM3 share a trusted LAN, prefer:

```text
RVW_ACCESS_MODE=local
RVW_BASE_URL=http://<device-hostname-or-lan-ip>
RVW_SYSTEM_PATH=
RVW_USERNAME=
RVW_PASSWORD=
```

The direct address must be the RVM3 itself, not `access.rvwhisper.com`. If the RVM3 serves its dashboard beneath a path instead of at its root, place that path in `RVW_SYSTEM_PATH`. A reserved DHCP address or stable local hostname prevents the address from changing.

Anonymous local reading is preferred where the RVM3 permits it. Administrator credentials printed on the device are not needed for normal read-only collection and must not be copied into GitHub. A future acknowledgement feature may require protected local credentials; the installer will collect them only after the vendor login flow is validated and the feature is explicitly enabled.

For gateway fallback, use `RVW_ACCESS_MODE=gateway`, `RVW_BASE_URL=https://access.rvwhisper.com`, and enter `RVW_USERNAME` and `RVW_PASSWORD`. Keep the initial poll interval at 60 seconds in either mode.

Capture one private sample from every discovered sensor:

```bash
sudo -u rvdashboard /opt/minnie-dashboard/current/backend/.venv/bin/rv-dashboard-capture \
  --env-file /etc/minnie-dashboard/dashboard.env
```

The command creates a timestamped, owner-only directory under `/var/lib/minnie-dashboard/captures`. Raw payloads may contain device names, room names, identifiers, or location-related data. Never commit or upload them without reviewing and redacting them.

## Create the real sensor map

Use the captured field names to replace the placeholder rules in:

```text
/etc/minnie-dashboard/sensor-map.json
```

Map only fields observed in real payloads. Do not infer watts, gallons, humidity, or energy source when RV Whisper does not report them. Confirm mappings for:

- battery state of charge, voltage, current, and power;
- shore connection, AC voltage, current, frequency, and reported power when available;
- dog area, coach, refrigerator, and freezer temperature;
- humidity only where a sensor actually reports it;
- fresh, gray, black, and propane percentages.

For a newly installed Power Watchdog, identify its captured file by sensor name and map only values actually present in that payload. Expected dashboard destinations are `power.ac.connected`, `power.ac.voltage`, `power.ac.current`, `power.ac.frequency`, and `power.ac.power`, but a destination must be omitted when the RVM3 payload does not provide a corresponding measurement. Do not calculate real power from volts multiplied by amps.

The optional built-in Wi-Fi Status sensor is useful diagnostic context. If installed, capture it like any other RVM3 sensor and map only observed fields under `network.rvm3.*` (for example signal or connectivity state when actually supplied). Its ten-minute reporting cadence must have a separate freshness threshold so the dashboard does not incorrectly mark it stale after the normal telemetry interval. This local sensor describes the RVM3's view of Wi-Fi; it is not a cloud-side proof that the gateway VPN is reachable.

## Customize names and sensor counts

The protected file `/etc/minnie-dashboard/dashboard-profile.json` controls presentation. The guided configuration tool is the preferred way to change the vehicle name and monogram, disable sections that are not installed, add or remove climate and tank items, edit labels, and choose Home items. Home intentionally displays at most four climate items and four tanks; all configured items appear on their diagnostic pages. Advanced users may still edit the JSON directly, but `rv-dashboard-configure --check` should be run afterward.

The profile contains normalized paths, never vendor serial numbers. The separate `/etc/minnie-dashboard/sensor-map.json` connects the owner's observed RV Whisper fields to those paths. Both files are preserved across upgrades and excluded from Git.

## Switch to live mode

After the sensor map is complete:

```bash
sudoedit /etc/minnie-dashboard/dashboard.env
sudo systemctl restart minnie-dashboard-api
sudo /opt/minnie-dashboard/current/deploy/verify-pi.sh
```

Change only `DASHBOARD_MODE=live`. Confirm that the header says **Live**, each detail card names a real source and observation time, stale values become visibly stale, and disconnecting the network does not leave old data looking current.

## Troubleshooting and rollback

```bash
journalctl -u minnie-dashboard-api -u minnie-dashboard-ui -n 200 --no-pager
systemctl restart minnie-dashboard-api minnie-dashboard-ui
ls -1 /opt/minnie-dashboard/releases
```

Each installer run creates a new release and changes the `current` symlink only after a successful build. To roll back, point `/opt/minnie-dashboard/current` at the preceding release and restart both services.

Back up `/etc/minnie-dashboard` and `/var/lib/minnie-dashboard/dashboard.db` privately. Do not place the environment file, real sensor map, database, or capture directories in GitHub.
