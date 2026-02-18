
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
| `RESOLUTION` | Capture resolution as `WIDTHxHEIGHT` | `960x540` |
| `KEYFILE` | Path to TLS private key (enables HTTPS) | *(disabled)* |
| `CERTFILE` | Path to TLS certificate chain (enables HTTPS) | *(disabled)* |
| `HDR` | Enable wide dynamic range mode (`1`/`0`). Requires `v4l-utils`. Applied before camera start on each service startup. | `0` |

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
