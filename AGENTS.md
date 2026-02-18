# AGENTS.md — picamera-streamer

## What this project is

A Raspberry Pi camera streaming server. It provides:
- `/stream.mjpg` — live MJPEG stream
- `/current.jpg` — single JPEG snapshot (fresh capture on each request)
- `/index.html` — simple HTML viewer page with the stream embedded
- `/status` — JSON health/info endpoint (name, uptime, resolution, HDR state, active clients, timestamp)
- `/` → redirects to `/index.html`

Runs as a systemd service (`picamera.service`). Configuration via a `.env` file.

## File map

```
picamera.py                    — main server (single file)
tools/
  getenv.py                    — .env parser (split on first = only)
  duckdns.py                   — DuckDNS IP updater (placeholder tokens, fill in locally)
systemd-files/
  picamera-monitor.service     — systemd one-shot for health check
  picamera-monitor.timer       — fires 1 min after boot, then every 5 min
  picamera-cert-deploy.sh      — generic template for certbot deploy hook (edit before use)
health_check.sh                — curl /current.jpg with timeout; restarts service on failure
sample.env                     — template for .env (committed; no real values)
picamera.service               — systemd service file for the streamer itself
```

## Configuration (.env)

| Key | Description | Default |
|---|---|---|
| `NAME` | Camera name | `Picamera` |
| `PORT` | Serve port | `8000` |
| `RESOLUTION` | `WIDTHxHEIGHT` | `960x540` |
| `KEYFILE` | TLS private key path (enables HTTPS) | disabled |
| `CERTFILE` | TLS cert chain path (enables HTTPS) | disabled |

`.env` is gitignored. `sample.env` is the committed placeholder with no real values.

## HDR

HDR is controlled via a systemd drop-in override, **not** `.env`. When `HDR=1` is set, the server runs `v4l2-ctl --set-ctrl wide_dynamic_range=1 -d /dev/v4l-subdev0` before the camera initialises. This is necessary because the setting resets on reboot and must be applied before the camera is opened. Requires `v4l-utils` (`sudo apt install v4l-utils`).

To enable HDR manually:

```bash
sudo mkdir -p /etc/systemd/system/picamera.service.d/
printf '[Service]\nEnvironment=HDR=1\n' | sudo tee /etc/systemd/system/picamera.service.d/hdr.conf
sudo systemctl daemon-reload && sudo systemctl restart picamera.service
```

To disable: `sudo rm /etc/systemd/system/picamera.service.d/hdr.conf && sudo systemctl daemon-reload && sudo systemctl restart picamera.service`

The `picamera-monitor` dashboard HDR On/Off buttons do this automatically via SSH. Do **not** add `HDR=` to `.env` — that file is for static config only.

## Known issues resolved (important context)

### Stream hang (fixed)
The original code used `condition.wait()` with no timeout. If the camera stalled, MJPEG stream handler threads blocked forever and the service appeared up but produced no output. Fixed by `condition.wait(timeout=5)` + `if frame is None: break`.

### Snapshot handler corruption (fixed)
Original code sent `send_response(200)` twice and sent headers before capturing the image, losing the content-length. Fixed: capture first, then send headers with correct `Content-Length`.

### SSL crash on Python 3.12 (fixed)
`ssl.wrap_socket` was removed in Python 3.12. Fixed by using `ssl.SSLContext` + `context.wrap_socket`.

### getenv parser broke on values containing = (fixed)
`split("=")` on a line like `CERTFILE=certificates/a=b` returned 3 parts. Fixed by `split("=", 1)`.

### Health check checked wrong endpoint (fixed)
`health_check.sh` was checking `http://localhost:8000/` (a redirect). This never triggered a restart for stream hangs. Fixed to check `/current.jpg` with `--max-time 10`.

## Certificate setup (HTTPS)

Both Pis use Let's Encrypt via certbot `--standalone`. The domain `geoclimatica.duckdns.org` resolves to a single external IP; Pi 1 and Pi 2 are port-forwarded on different ports (8022/8033 for SSH, 8000 for the streamer). Certbot runs on Pi 1 only.

**Auto-renewal on cert change:**
A deploy hook at `/etc/letsencrypt/renewal-hooks/deploy/picamera-streamer.sh` (on Pi 1, local only — not in the repo):
1. Copies fresh certs into `~/picamera-streamer/certificates/`
2. Restarts `picamera.service` on Pi 1
3. SCPs the certs to Pi 2 and restarts its service via SSH

Pi 1 → Pi 2 key-based SSH is required for step 3. Pi 1's key (`lee@geoone`) is in Pi 2's `~/.ssh/authorized_keys`. `systemd-files/picamera-cert-deploy.sh` is a generic template version showing the pattern; the live hook on Pi 1 is configured with real paths and is not committed.

If Let's Encrypt symlinks under `/etc/letsencrypt/live/` are missing (can happen after a failed renewal), recreate them pointing at the most recent complete archive set before running `certbot renew`.

## Dual-Pi setup

| | Pi 1 (geoone) | Pi 2 (geotwo) |
|---|---|---|
| SSH port | 8022 | 8033 |
| Stream port | 8000 | 8000 |
| Camera name | Valleycam | Coitycam |
| Certbot | Installed, renews | Copies from Pi 1 |
| Health check timer | Installed | Installed |

Both Pis run the same code from the same repo. Pi-specific settings (NAME, HDR, certs) live in `.env` on each Pi.

## Development workflow

```bash
git clone git@github.com:gogeouk/picamera-streamer.git
cp sample.env .env
# Edit .env
sudo python picamera.py
```

To deploy a change to both Pis:
```bash
git push
ssh lee@home.geoclimatica.com -p 8022 'cd ~/picamera-streamer && git pull && sudo systemctl restart picamera.service'
ssh lee@home.geoclimatica.com -p 8033 'cd ~/picamera-streamer && git pull && sudo systemctl restart picamera.service'
```

## What must never be committed

- `.env` (real camera config, KEYFILE/CERTFILE paths)
- `certificates/` (TLS certs and keys)
- `.vscode/sftp.json` (contains SSH passwords)
- Any file with real hostnames (`geoclimatica.duckdns.org`, `home.geoclimatica.com`) or credentials

The `.gitignore` covers all of the above. The `systemd-files/picamera-cert-deploy.sh` in the repo is a generic template only — the live version on Pi 1 contains real paths and is not committed.
