#!/usr/bin/python3

# Mostly copied from https://picamera.readthedocs.io/en/release-1.13/recipes2.html
# Run this script, then point a web browser at http:<this-ip-address>:8000
# Note: needs simplejpeg to be installed (pip3 install simplejpeg).

# Licence for original code: https://github.com/raspberrypi/picamera2?tab=BSD-2-Clause-1-ov-file#readme

import io
import json
import logging
import os
import socketserver
import ssl
import subprocess
import time
from datetime import datetime, timezone
from http import server
from threading import Condition, Lock, Timer
from tools.getenv import get_env_var

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, MJPEGEncoder
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
# Frames a second sent to each viewer. The camera and the minute-by-minute
# snapshots are unaffected: this only decides how often an encoded frame is kept
# and sent. At the camera's own rate a single viewer pulled 15-17 Mbit/s from a
# domestic upload, which is most of why the live view stalled; 5 fps is about
# 3.5 Mbit/s and still shows a bird crossing the frame.
STREAM_FPS = float(get_env_var("STREAM_FPS", 5))
# Which encoder makes the stream's JPEGs.
#   jpeg   software (simplejpeg) on the full-size frames: about 215% CPU on a Pi 3B
#          for as long as anyone is watching.
#   mjpeg  the Pi's hardware JPEG encoder, fed by the camera's small stream
#          (RESOLUTION, default 960x540, the largest any page shows it). It accepts
#          that stream's YUV420, which the software encoder does not.
STREAM_ENCODER = get_env_var("STREAM_ENCODER", "jpeg").strip().lower()
# Bits a second for the hardware encoder, before the rate cap throws frames away:
# 8 Mbit/s at the camera's rate is roughly 40 KB a frame.
MJPEG_BITRATE = int(get_env_var("MJPEG_BITRATE", 8_000_000))
# Where the viewing counts are kept, so a restart does not lose the day's totals.
# The service cannot write to its own folder (ProtectHome=read-only) and its /tmp is
# wiped on restart (PrivateTmp), so this goes in the state directory systemd makes
# for it: StateDirectory=picamera, which is /var/lib/picamera, owned by the service
# user. Falls back to the working directory when run by hand.
STATS_FILE = get_env_var("STATS_FILE", os.path.join(os.environ.get("STATE_DIRECTORY", "."), "stream-stats.json"))

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
            if STREAM_ENCODER == "mjpeg":
                _encoder = MJPEGEncoder(bitrate=MJPEG_BITRATE)
                picam2.start_encoder(_encoder, FileOutput(output), name="lores")
            else:
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

class ViewingStats:
    """How much the live stream is watched, per UTC day. No addresses, no
    identifiers: how many sessions started, how many seconds were watched in
    total, and the most viewers at once. Kept in a small file so a restart or a
    power cut does not lose the day, and reported in /status for the daily
    digest, which is how we will know whether a relay is worth building.
    """

    def __init__(self, path):
        self.path = path
        self.lock = Lock()
        self.data = {"day": self._today(), "today": self._empty(), "yesterday": self._empty()}
        try:
            with open(self.path) as f:
                saved = json.load(f)
            if {"day", "today", "yesterday"} <= saved.keys():
                self.data = saved
        except Exception:
            pass  # first run, or unreadable: start counting from now

    @staticmethod
    def _today():
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _empty():
        return {"sessions": 0, "seconds": 0, "peak_viewers": 0}

    def _roll(self):
        today = self._today()
        if self.data["day"] == today:
            return
        # More than a day idle: yesterday's counts are no longer yesterday's.
        gap = (datetime.fromisoformat(today) - datetime.fromisoformat(self.data["day"])).days
        self.data = {
            "day": today,
            "today": self._empty(),
            "yesterday": self.data["today"] if gap == 1 else self._empty(),
        }

    def _save(self):
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except Exception as e:
            logging.warning("Could not save viewing stats: %s", e)

    def session_started(self, viewers_now):
        with self.lock:
            self._roll()
            self.data["today"]["sessions"] += 1
            self.data["today"]["peak_viewers"] = max(self.data["today"]["peak_viewers"], viewers_now)
            self._save()

    def session_ended(self, seconds):
        with self.lock:
            self._roll()
            self.data["today"]["seconds"] += int(seconds)
            self._save()

    def snapshot(self):
        with self.lock:
            self._roll()
            return {"day": self.data["day"], "today": dict(self.data["today"]),
                    "yesterday": dict(self.data["yesterday"])}


stats = ViewingStats(STATS_FILE)

print("Loading picamera streamer")


class StreamingOutput(io.BufferedIOBase):
    """The latest encoded frame, at no more than STREAM_FPS a second.

    Frames arriving sooner than that are dropped here rather than sent, which is
    what keeps a viewer's bandwidth (and John's upload) down. The encoder is also
    asked to skip frames, but this gate is what guarantees the rate.
    """

    def __init__(self):
        self.frame = None
        self.frame_at = None
        self.condition = Condition()
        self._interval = 1.0 / STREAM_FPS if STREAM_FPS > 0 else 0.0
        self._last_kept = 0.0

    def write(self, buf):
        now = time.monotonic()
        if self._interval and self.frame is not None and now - self._last_kept < self._interval:
            return
        self._last_kept = now
        with self.condition:
            self.frame = buf
            self.frame_at = time.time()
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
                # The weather site reads these from its own origin.
                self.send_header('Access-Control-Allow-Origin', '*')
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
                "stream_fps": STREAM_FPS,
                "stream_encoder": STREAM_ENCODER,
                "clients": active_clients,
                "max_clients": MAX_STREAM_CLIENTS,
                "viewing": stats.snapshot(),
                "encoder_running": encoder_running(),
                "cert_expires": cert_expires,
                "cert_days_remaining": cert_days,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            content = json.dumps(status).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(content))
            self.send_header('Access-Control-Allow-Origin', '*')
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
                viewers_now = active_clients
            stats.session_started(viewers_now)
            session_started_at = time.monotonic()
            try:
                # Not holding active_clients_lock here — see lock ordering note.
                acquire_encoder()
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
                # The player reads this stream frame by frame from another origin,
                # so it can show the time on each frame, notice a stall and reconnect.
                self.send_header('Access-Control-Allow-Origin', '*')
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
                        frame_at = output.frame_at
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
                    # When this frame was taken, so the viewer can show the time on
                    # it and see at once when the picture has stopped moving.
                    self.send_header('X-Timestamp', f"{frame_at:.3f}" if frame_at else "")
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
                stats.session_ended(time.monotonic() - session_started_at)
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
# The full-size stream feeds /current.jpg, and so the weather site's minute-by-minute
# captures; the small one exists only for the hardware encoder.
video_config = (
    picam2.create_video_configuration(main={"size": (1280, 720)}, lores={"size": (int(width), int(height))})
    if STREAM_ENCODER == "mjpeg"
    else picam2.create_video_configuration({"size": (1280, 720)})
)
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
