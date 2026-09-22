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
health_check.sh                — curl /current.jpg with timeout; retries once after 20 s, restarts only if both fail
monitor-gate.sh                — the ONLY command the dashboard's SSH key may run (forced command in authorized_keys)
cert-receive.sh                — the ONLY command the certificate-sync key may run on the peer Pi
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

## Live stream rate

`STREAM_FPS` (default 5) caps what each viewer is sent, and the stream is encoded
from a second, smaller camera stream (`RESOLUTION`, default 960×540); `/current.jpg`
and the weather site's captures still come from the full-size stream, unchanged.
(picamera2's `frame_skip_count` looks like a rate control but does nothing in
0.3.23: it is not read anywhere in the installed package.) Every frame carries `X-Timestamp`, and the three
public endpoints allow cross-origin reads, because the site's player reads the stream
frame by frame (stall detection, reconnect, showing the time on the picture).
`/status` also reports anonymous viewing counts, kept in `/var/lib/picamera/`
(`StateDirectory=picamera`).

### CPU while someone watches (open)

Encoding the stream costs about 215% CPU on a Pi 3B, and the 5 fps cap does not
change that: every frame is still encoded and the extras are dropped afterwards.
Two dead ends, so nobody repeats them:

- `frame_skip_count` on the encoder looks like a rate control but is not read
  anywhere in picamera2 0.3.23. Setting it does nothing.
- Encoding the camera's small (`lores`) stream instead fails: on this pipeline that
  stream is YUV420, and `JpegEncoder` has no entry for it
  (`KeyError: 'YUV420'`, 22 Sep 2026). Tried and reverted.

The promising route is `MJPEGEncoder`, which uses the Pi's hardware JPEG encoder and
does accept YUV420, so it could encode the small stream at a fraction of the CPU.
Test it with the service stopped, between captures, before deploying. The cost is
only paid while someone is watching (the encoder is on demand), so this is
worth doing but not urgent.

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

### Health check never ran — leading blank line before the shebang (fixed 2026-08-23)

`health_check.sh` had an empty first line, so `#!/bin/bash` started at byte 1 instead of
byte 0. The kernel requires the shebang at byte 0, so every invocation failed with
`Exec format error` (systemd `status=203/EXEC`). The timer had been firing every five
minutes on both Pis for months and **had never once executed the script** — no
`picamera_health.log` existed on either machine.

This is why Valleycam sat dead for three hours on 2026-08-23 despite the auto-restart
timer being installed, enabled and active. Diagnose with
`systemctl status picamera-monitor.service`, not by reading the timer state.

### The streamer runs as its own user (2026-09-22)

`picamera.service` answers the internet on :8000. It used to run as `lee`, who has
passwordless sudo, so any exploitable bug in it was root on the Pi. It now runs as
the system user `picamera`: `video` group for the camera, read access to its own
code, `.env` and TLS key (`privkey.pem` is `640 lee:picamera`), `NoNewPrivileges`,
and nothing else. `lee`'s home is `711`, with everything except `picamera-streamer`
closed to other users. `lee`'s account password is locked; logins are key-only.

Set up by `sudo systemd-files/setup-service-user.sh` (idempotent), which installs
the drop-in `systemd-files/picamera-user.conf`, then `systemctl restart picamera`.
Undo: remove `/etc/systemd/system/picamera.service.d/user.conf`, `daemon-reload`,
restart.

**After any `git pull` that touches the certificate hook, reinstall it** (the setup
script does this): certbot runs the copy in `/etc/letsencrypt/renewal-hooks/deploy/`,
not the one in this repo. An old copy resets the key to `600 lee:lee`, and the
streamer then cannot start.

### Who can log in where (2026-09-21)

Both Pis serve one DuckDNS name, so only geoone renews the certificate (certbot
`standalone`: the router forwards port 80 to geoone for the challenge). Its deploy
hook then pushes the certificate to geotwo. That push used to go through lee's
ordinary key on geoone, which geotwo trusted without limit: owning one Pi meant owning
both. Now:

| Key | Accepted by | Can do |
|---|---|---|
| Lee's own (`code@corbin.uk`) | both Pis | anything |
| `picamera-monitor@ontoast` | both Pis | `monitor-gate.sh` verbs only |
| `cert-sync@geoone` (root-owned, `/etc/picamera-cert-deploy/`) | geotwo | `cert-receive.sh`: install a certificate that is valid, matches its key, covers the same names and is not older |

geoone's own `lee@geoone` key is no longer accepted anywhere. The hook pins geotwo's
host keys (`/etc/picamera-cert-deploy/known_hosts`). Test between renewals with
`sudo /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh --check`, which
changes nothing; `certbot renew --dry-run` tests the renewal itself. Both passed on
2026-09-21.

### The dashboard's SSH key is fenced in by monitor-gate.sh (2026-09-21)

`cams.gogeo.uk` (picamera-monitor) controls this Pi over SSH. Until 2026-09-21 it did
so with lee's personal key, which has passwordless root here, mounted into a
web-facing container. It now has its own key, installed in `~/.ssh/authorized_keys`
as:

    restrict,command="/home/lee/picamera-streamer/monitor-gate.sh" ssh-ed25519 AAAA... picamera-monitor@ontoast

so it can only `probe`, `start`, `stop`, `restart`, `hdr-on` or `hdr-off`. Anything
else is refused and logged (`journalctl -t monitor-gate`). If the dashboard needs a new
ability, add a verb to the gate; never loosen the key.

### Health check restarted healthy cameras under load (fixed 2026-09-21)

A single probe that took longer than 10 seconds restarted the service. On a Pi 3 that
happens to a perfectly healthy camera whenever the machine is busy: an `apt` run on
geoone on 2026-09-21 did exactly that, and the restart itself caused the outage. geoone
was also being restarted about one and a half times a day at the time, while Raspberry Pi
Connect's screen-sharing process crash-looped every few seconds on it (since removed),
so some of those were probably the same false alarm. The check now waits 20 seconds and
probes again, and restarts only if both probes fail. The journal says
`slow once, then ok` when the retry saved a restart; count those before assuming a
camera problem.

### Health check probed the wrong protocol (fixed 2026-08-23)

The script probed `http://localhost:8000/current.jpg`, but both Pis serve **HTTPS**
(`KEYFILE`/`CERTFILE` are set in `.env`). Even with the shebang fixed it would have
failed every run and restarted the service every five minutes. It now reads `PORT` and
`KEYFILE` from `.env` and probes the scheme actually in use, with `-k` because the
certificate is issued for the public hostname rather than `localhost`.

Output now goes to the journal (`journalctl -u picamera-monitor.service`) rather than a
file that grows without bound.

### MJPEG handler threads leaked until the process wedged (fixed 2026-08-23)

The stream loop had no socket timeout. A viewer that disappeared without closing the
connection — mobile losing signal, NAT entry expiring, browser tab discarded — never sent
FIN or RST, so `self.wfile.write()` blocked indefinitely and the handler thread was never
reclaimed. The public weather site embeds the stream, so every visitor is a potential leak.

Measured on geotwo at 22 days uptime: **566 threads**, against 14 on a freshly restarted
geoone. Each leaked thread wakes on `condition.wait(timeout=5)`, so idle overhead grows
without bound until the process can no longer service requests — including `/status`, which
touches no camera hardware at all. A `/status` timeout is therefore the signature of this
leak rather than of a camera fault.

Fixed with three limits, all overridable in `.env`:

| Setting | Default | Purpose |
|---|---|---|
| `MAX_STREAM_CLIENTS` | 8 | Refuse further viewers with 503 rather than spawning unbounded threads |
| `STREAM_CLIENT_TIMEOUT` | 20 | Socket write timeout, so a dead peer raises instead of blocking |
| `STREAM_STALL_TIMEOUT` | 15 | Drop a client if the camera produces no new frame, instead of re-sending a stale one forever |

### Known, not yet fixed

- **The encoder runs continuously even with zero viewers.** Both Pis sit at ~215% CPU
  permanently. `start_recording()` encodes regardless of demand; only the encoder needs to
  stop when idle, as `/current.jpg` uses `capture_file()` and needs the camera itself running.
- **`RESOLUTION` does not configure the camera.** `create_video_configuration` hardcodes
  `1280x720`; the env var only sets the `<img>` dimensions on the viewer page. Lowering the
  real capture resolution is the cheapest thermal win available.
- **geoone runs hot.** 77.4 °C versus 54.8 °C on geotwo, identical hardware (Pi 3B) and
  identical load. `get_throttled` reports `0x70005` on both — under-voltage and throttling
  active now, plus historical frequency capping. Enclosure and power supply, not software.

## Certificate setup (HTTPS)

Both Pis use Let's Encrypt via certbot `--standalone`. The domain `your-domain.duckdns.org` resolves to a single external IP; Pi 1 and Pi 2 are port-forwarded on different ports (<pi1-ssh-port>/<pi2-ssh-port> for SSH, 8000 for the streamer). Certbot runs on Pi 1 only.

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
| SSH port | <pi1-ssh-port> | <pi2-ssh-port> |
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
ssh lee@pi-host.example.com -p <pi1-ssh-port> 'cd ~/picamera-streamer && git pull && sudo systemctl restart picamera.service'
ssh lee@pi-host.example.com -p <pi2-ssh-port> 'cd ~/picamera-streamer && git pull && sudo systemctl restart picamera.service'
```

## What must never be committed

- `.env` (real camera config, KEYFILE/CERTFILE paths)
- `certificates/` (TLS certs and keys)
- `.vscode/sftp.json` (contains SSH passwords)
- Any file with real hostnames (`your-domain.duckdns.org`, `pi-host.example.com`) or credentials

The `.gitignore` covers all of the above. The `systemd-files/picamera-cert-deploy.sh` in the repo is a generic template only — the live version on Pi 1 contains real paths and is not committed.
