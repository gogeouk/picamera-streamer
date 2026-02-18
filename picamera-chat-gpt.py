#!/usr/bin/python3

import io
import logging
import socketserver
import ssl
import time
import signal
from http import server
from threading import Condition
from tools.getenv import get_env_var

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
from libcamera import controls

width, height = map(int, get_env_var("RESOLUTION", "960x540").split("x"))

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
        try:
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
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'image/jpeg')
                self.end_headers()
                with io.BytesIO() as data:
                    picam2.capture_file(data, format='jpeg')
                    if data.getvalue() == b"":
                        self.send_error(404, "Image Not Found")
                        return
                    self.wfile.write(data.getvalue())
            elif self.path == '/stream.mjpg':
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
                self.end_headers()
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    try:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', len(frame))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    except (BrokenPipeError, ConnectionResetError):
                        logging.warning(f"Client {self.client_address} disconnected.")
                        break
            else:
                self.send_error(404)
                self.end_headers()
        except Exception as e:
            logging.error(f"Error in GET request: {e}")


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def stop_server(signum, frame):
    print("Stopping server...")
    picam2.stop_recording()
    server.shutdown()


# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, stop_server)
signal.signal(signal.SIGTERM, stop_server)

picam2 = Picamera2()
video_config = picam2.create_video_configuration({"size": (width, height)})
picam2.configure(video_config)

picam2.set_controls({"ScalerCrop": (0, 0, 4008, 2250)})
time.sleep(5)

output = StreamingOutput()
try:
    picam2.start_recording(JpegEncoder(), FileOutput(output))
except Exception as e:
    logging.error(f"Failed to start recording: {e}")
    raise

try:
    port = int(get_env_var("PORT", 8000))
    address = ('', port)
    server = StreamingServer(address, StreamingHandler)
    if get_env_var("KEYFILE", False):
        server.socket = ssl.wrap_socket(
            server.socket,
            keyfile=get_env_var("KEYFILE"),
            certfile=get_env_var("CERTFILE"),
            server_side=True
        )
    logging.info(f"Starting picamera streamer on port {port}")
    server.serve_forever()
finally:
    picam2.stop_recording()
