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

Leave `DASHBOARD_MODE=demo` while entering `RVW_ID`, `RVW_USERNAME`, and `RVW_PASSWORD`. Keep the initial poll interval at 60 seconds.

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
