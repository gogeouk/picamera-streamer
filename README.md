
## Introduction
Picamera Streamer is a modified version of one of the [Raspberry Pi picamera2](https://github.com/raspberrypi/picamera2) sample files: it provides an HTTP live stream (MJPEG) of the camera as well as a snapshot endpoint.
These two endpoints are used by the webcam feature in GoGeo's weather monitoring server.

## Installation

These instructions get the server running as a `systemd` service so it starts on boot and restarts automatically on failure.

Latest versions of Raspberry Pi OS include camera support out of the box.

1. Physically install the camera onto the Pi.
2. Download the latest Raspberry Pi Imager and flash an SD card with Raspberry Pi OS (use Edit Settings to configure login, SSH, wifi etc. during imaging).
3. Boot the Pi, complete any remaining setup, and SSH in.
4. Clone this repo into your home directory:

        git clone https://github.com/gogeouk/picamera-streamer.git
        cd picamera-streamer

5. If necessary, install the picamera2 library:

        pip3 install picamera2

6. Create a `.env` file (see **Configuration** below).
7. **TEST** run the script directly:

        python3 picamera.py

8. **TEST** open `http://<pi-address>:8000` in a browser for live video.
9. **TEST** open `http://<pi-address>:8000/current.jpg` for a snapshot.
10. Edit `picamera.service` — update `User`, `WorkingDirectory` and `ExecStart` to match your username and install path.
11. Install and enable the service:

        sudo cp picamera.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable picamera.service
        sudo systemctl start picamera.service

## Configuration

Create a `.env` file in the project directory to configure the service. A `sample.env` file is provided as a starting point.

| Key | Description | Default |
|---|---|---|
| `NAME` | Camera name shown on the stream page | `Picamera` |
| `PORT` | HTTP/HTTPS port to serve on | `8000` |
| `RESOLUTION` | Live stream resolution as `WIDTHxHEIGHT` (snapshots are always 1280x720) | `960x540` |
| `STREAM_FPS` | Frames a second sent to each viewer | `5` |
| `STREAM_ENCODER` | `mjpeg` (the Pi's hardware encoder) or `jpeg` (software) | `mjpeg` |
| `MJPEG_BITRATE` | Quality of the hardware encoder, in bits a second | `8000000` |
| `KEYFILE` | Path to TLS private key (enables HTTPS) | *(disabled)* |
| `CERTFILE` | Path to TLS certificate chain (enables HTTPS) | *(disabled)* |

### Live stream rate

`STREAM_FPS` (default 5) is how many frames a second each viewer is sent. At the
camera's own rate one viewer pulled **15–17 Mbit/s** from a domestic upload, which is
most of why the live view stalled and why a forgotten tab was so costly; 5 fps is
about 1.2 Mbit/s and still shows a bird crossing the frame. Frames above the rate are
dropped before being sent.

The stream is encoded by the **Pi's hardware JPEG encoder** (`STREAM_ENCODER=mjpeg`)
from a second, smaller camera stream at `RESOLUTION` — 960x540, the largest any page
shows it. Measured on Coitycam, 22 September 2026: **72% CPU** while someone watches
against 215% for the software encoder, and **34 KB a frame** against 52.
`STREAM_ENCODER=jpeg` goes back to the software encoder on full-size frames, and a
board with no hardware encoder (a Pi 5) falls back to it by itself, with a line in
the journal.

**None of this touches the camera**: exposure, `/current.jpg` and the weather site's
minute-by-minute captures are full size (1280x720) and exactly as before.

Each frame in the stream carries an `X-Timestamp` header (seconds since the epoch)
so a viewer can show the time the picture was taken and see when it has stopped
moving. `/stream.mjpg`, `/current.jpg` and `/status` send
`Access-Control-Allow-Origin: *`, which is what lets the weather site read the
stream frame by frame rather than handing it to an `<img>` and hoping.

### Viewing counts

`/status` reports `viewing`: sessions, seconds watched and the most viewers at once,
for today and yesterday (UTC). No addresses and no identifiers. They are kept in
`$STATE_DIRECTORY/stream-stats.json` (`/var/lib/picamera/`, made by systemd for the
service user), so a restart does not lose the day, and they answer the question of
whether a relay is worth building.

### HDR (wide dynamic range)

HDR is controlled via a systemd drop-in override, not `.env`. To enable it manually:

    sudo mkdir -p /etc/systemd/system/picamera.service.d/
    printf '[Service]\nEnvironment=HDR=1\n' | sudo tee /etc/systemd/system/picamera.service.d/hdr.conf
    sudo systemctl daemon-reload && sudo systemctl restart picamera.service

To disable:

    sudo rm /etc/systemd/system/picamera.service.d/hdr.conf
    sudo systemctl daemon-reload && sudo systemctl restart picamera.service

If you use `picamera-monitor`, the HDR On/Off buttons do this automatically. Requires `v4l-utils` (`sudo apt install v4l-utils`).

## Automatic health check

A systemd timer is included that checks the stream every 5 minutes and restarts the service if it has stopped responding. To install it:

    sudo cp systemd-files/picamera-monitor.service /etc/systemd/system/
    sudo cp systemd-files/picamera-monitor.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable picamera-monitor.timer
    sudo systemctl start picamera-monitor.timer

## HTTPS with automatic certificate renewal

Modern browsers require HTTPS to display camera streams. The recommended approach is to use [Let's Encrypt](https://letsencrypt.org/) via `certbot` with automatic renewal.

### Initial setup

1. Install certbot:

        sudo apt-get install certbot

2. Obtain a certificate. certbot uses port 80 for the HTTP challenge, so port 80 must be forwarded to your Pi on your router during this step:

        sudo certbot certonly --standalone -d your-domain.example.com

3. Create the `certificates/` directory and copy the certs in:

        mkdir -p certificates
        sudo cp /etc/letsencrypt/live/your-domain.example.com/fullchain.pem certificates/
        sudo cp /etc/letsencrypt/live/your-domain.example.com/privkey.pem certificates/
        sudo chown $USER:$USER certificates/*.pem
        chmod 600 certificates/privkey.pem

4. Add `KEYFILE` and `CERTFILE` to your `.env`:

        KEYFILE=certificates/privkey.pem
        CERTFILE=certificates/fullchain.pem

5. Restart the service:

        sudo systemctl restart picamera.service

### Automatic renewal

certbot renews certificates automatically via a system timer. To make it also copy the new certs into place and restart the streamer, install the included deploy hook:

1. Edit `systemd-files/picamera-cert-deploy.sh` — update `DOMAIN`, `DEST_DIR`, and the `chown` username to match your setup.
2. Install it:

        sudo cp systemd-files/picamera-cert-deploy.sh /etc/letsencrypt/renewal-hooks/deploy/
        sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh

After this, every time certbot renews the certificate (typically every 60 days), the new certs will be deployed and the service restarted automatically — no manual intervention needed.
