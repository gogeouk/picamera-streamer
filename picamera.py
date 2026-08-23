#!/usr/bin/python3

# Mostly copied from https://picamera.readthedocs.io/en/release-1.13/recipes2.html
# Run this script, then point a web browser at http:<this-ip-address>:8000
# Note: needs simplejpeg to be installed (pip3 install simplejpeg).

# Licence for original code: https://github.com/raspberrypi/picamera2?tab=BSD-2-Clause-1-ov-file#readme

import io
import json
import logging
import socketserver
import ssl
import subprocess
import time
from datetime import datetime, timezone
from http import server
from threading import Condition, Lock, Timer
from tools.getenv import get_env_var

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
width, height = get_env_var("RESOLUTION", "960x540").split("x")
hdr_enabled = get_env_var("HDR", "0").strip().lower() in ("1", "true", "yes")

start_time = time.time()
active_clients = 0
active_clients_lock = Lock()

# Concurrent MJPEG viewers allowed. Each one costs a thread; the public weather
# site embeds the stream, so without a ceiling a burst of visitors can pin the Pi.
MAX_STREAM_CLIENTS = int(get_env_var("MAX_STREAM_CLIENTS", 8))
# Socket write timeout for a stream client. A viewer that disappears without
# closing (mobile losing signal, NAT entry expiring, tab discarded) never sends
# FIN or RST, so a blocking write would wait indefinitely and leak the thread.
STREAM_CLIENT_TIMEOUT = int(get_env_var("STREAM_CLIENT_TIMEOUT", 20))
# Give up on a client if the camera produces no new frame for this long.
STREAM_STALL_TIMEOUT = int(get_env_var("STREAM_STALL_TIMEOUT", 15))

_cert_cache = {"checked_at": 0.0, "expires": None, "days_remaining": None}

# How long the encoder keeps running after the last viewer leaves. Stops a page
# refresh or a viewer flicking between cameras from thrashing the encoder.
ENCODER_LINGER = int(get_env_var("ENCODER_LINGER", 20))
# How long a connecting viewer waits for the first frame after a cold start.
ENCODER_START_TIMEOUT = int(get_env_var("ENCODER_START_TIMEOUT", 10))

encoder_lock = Lock()
_encoder = None
_encoder_stop_timer = None

# Lock ordering, to avoid deadlock: encoder_lock is always taken BEFORE
# active_clients_lock, never the other way round. Callers must not hold
# active_clients_lock when calling acquire_encoder()/release_encoder().


def acquire_encoder():
    """Start the JPEG encoder if it is not already running.

    The camera itself runs continuously (snapshots need it), but the encoder
    only needs to run while someone is actually watching the live stream.
    Encoding continuously regardless of demand kept both Pis at ~215% CPU
    permanently, which on a thermally throttled Pi 3B is most of the reason
    they became unstable.
    """
    global _encoder, _encoder_stop_timer
    with encoder_lock:
        if _encoder_stop_timer is not None:
            _encoder_stop_timer.cancel()
            _encoder_stop_timer = None
        if _encoder is None:
            output.frame = None  # don't serve a stale frame from the last session
            _encoder = JpegEncoder()
            picam2.start_encoder(_encoder, FileOutput(output))
            logging.info("Encoder started (viewer connected)")


def release_encoder():
    """Schedule the encoder to stop once the last viewer has gone."""
    global _encoder_stop_timer
    with encoder_lock:
        if _encoder_stop_timer is not None:
            _encoder_stop_timer.cancel()
        _encoder_stop_timer = Timer(ENCODER_LINGER, _stop_encoder_if_idle)
        _encoder_stop_timer.daemon = True
        _encoder_stop_timer.start()


def _stop_encoder_if_idle():
    global _encoder, _encoder_stop_timer
    with encoder_lock:
        _encoder_stop_timer = None
        with active_clients_lock:
            if active_clients > 0:
                return
        if _encoder is not None:
            try:
                picam2.stop_encoder()
                logging.info("Encoder stopped (no viewers)")
            except Exception as e:
                logging.warning("Could not stop encoder: %s", e)
            _encoder = None
            output.frame = None


def encoder_running():
    with encoder_lock:
        return _encoder is not None


def cert_status():
    """Expiry of the TLS certificate we are serving, refreshed hourly.

    Surfaced in /status so the monitoring dashboard can warn before a cert
    expires rather than after. An expired cert takes the camera off the weather
    site silently: browsers refuse the stream but the service itself looks
    perfectly healthy from the Pi's point of view.
    """
    certfile = get_env_var("CERTFILE", "")
    if not certfile:
        return None, None

    now = time.time()
    if now - _cert_cache["checked_at"] < 3600 and _cert_cache["expires"] is not None:
        return _cert_cache["expires"], _cert_cache["days_remaining"]

    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", certfile],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None, None
        # Format: notAfter=Nov 14 08:56:10 2026 GMT
        raw = result.stdout.strip().split("=", 1)[1].replace(" GMT", "")
        expiry = datetime.strptime(raw, "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
        days = (expiry - datetime.now(timezone.utc)).days
        _cert_cache.update(
            checked_at=now, expires=expiry.isoformat(), days_remaining=days
        )
        return _cert_cache["expires"], days
    except Exception as e:
        logging.warning("Could not read certificate expiry: %s", e)
        return None, None

PAGE = f"""\
<html>
<head>
<title>{get_env_var("NAME", "Picamera")}</title>
</head>
<body>
<h1>{get_env_var("NAME", "Picamera")} Live</h1>
<img src="stream.mjpg" width="{width}" height="{height}" />
</body>
</html>
"""

print("Loading picamera streamer")


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        global active_clients, active_clients_lock
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/current.jpg':
            try:
                data = io.BytesIO()
                picam2.capture_file(data, format='jpeg')
                if data.getvalue() == b"":
                    self.send_error(404, "Image Not Found")
                    return
                image = data.getvalue()
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', len(image))
                self.end_headers()
                self.wfile.write(image)
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        elif self.path == '/status':
            cert_expires, cert_days = cert_status()
            status = {
                "name": get_env_var("NAME", "Picamera"),
                "uptime_seconds": int(time.time() - start_time),
                "resolution": f"{width}x{height}",
                "hdr": hdr_enabled,
                "clients": active_clients,
                "max_clients": MAX_STREAM_CLIENTS,
                "encoder_running": encoder_running(),
                "cert_expires": cert_expires,
                "cert_days_remaining": cert_days,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            content = json.dumps(status).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            with active_clients_lock:
                if active_clients >= MAX_STREAM_CLIENTS:
                    logging.warning(
                        'Refusing stream client %s: at limit of %d',
                        self.client_address, MAX_STREAM_CLIENTS)
                    self.send_error(503, 'Too many streaming clients')
                    return
                active_clients += 1
            try:
                # Not holding active_clients_lock here — see lock ordering note.
                acquire_encoder()
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
                self.end_headers()

                # Without this the write below can block forever on a client that
                # went away without closing the socket, and the handler thread is
                # never reclaimed. That leak is what wedges the service: geotwo
                # accumulated 566 threads over 22 days of uptime.
                self.connection.settimeout(STREAM_CLIENT_TIMEOUT)

                # Cold start: the encoder was idle, so wait for its first frame
                # rather than treating the empty buffer as end-of-stream.
                deadline = time.monotonic() + ENCODER_START_TIMEOUT
                with output.condition:
                    while output.frame is None and time.monotonic() < deadline:
                        output.condition.wait(timeout=1)
                    first_frame = output.frame
                if first_frame is None:
                    logging.warning('Encoder produced no frame within %ss for %s',
                                    ENCODER_START_TIMEOUT, self.client_address)
                    return

                last_frame_at = time.monotonic()
                while True:
                    with output.condition:
                        got_frame = output.condition.wait(timeout=5)
                        frame = output.frame
                    if frame is None:
                        break
                    if not got_frame:
                        # Camera produced nothing new. Re-sending the same stale
                        # frame indefinitely hides the stall from the viewer, so
                        # drop the connection and let them reconnect.
                        if time.monotonic() - last_frame_at > STREAM_STALL_TIMEOUT:
                            logging.warning(
                                'No new frame for %ss, dropping client %s',
                                STREAM_STALL_TIMEOUT, self.client_address)
                            break
                        continue
                    last_frame_at = time.monotonic()
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
            finally:
                with active_clients_lock:
                    active_clients -= 1
                release_encoder()
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


if hdr_enabled:
    subprocess.run(
        ["v4l2-ctl", "--set-ctrl", "wide_dynamic_range=1", "-d", "/dev/v4l-subdev0"],
        check=False
    )
    print("HDR enabled")

picam2 = Picamera2()
video_config = picam2.create_video_configuration({"size": (1280, 720)})
picam2.configure(video_config)

picam2.set_controls({"ScalerCrop": (0, 0, 4008, 2250)})
time.sleep(5)

output = StreamingOutput()
# Camera on, encoder off. /current.jpg uses capture_file() which only needs the
# camera running; the encoder is started on demand by the first stream viewer.
picam2.start()

try:
    port = int(get_env_var("PORT", 8000))
    address = ('', port)
    server = StreamingServer(address, StreamingHandler)
    if (get_env_var("KEYFILE", False)):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=get_env_var("CERTFILE"), keyfile=get_env_var("KEYFILE"))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Starting picamera streamer on port {port}")
    server.serve_forever()
finally:
    picam2.stop()
