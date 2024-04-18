#!/usr/bin/python3

# Mostly copied from https://picamera.readthedocs.io/en/release-1.13/recipes2.html
# Run this script, then point a web browser at http:<this-ip-address>:8000
# Note: needs simplejpeg to be installed (pip3 install simplejpeg).

# Licence for original code: https://github.com/raspberrypi/picamera2?tab=BSD-2-Clause-1-ov-file#readme

import io
import logging
import socketserver
import ssl
from http import server
from threading import Condition
from tools.getenv import get_env_var

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput

width, height = get_env_var("RESOLUTION", "960x540").split("x")

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
            try:
                data = io.BytesIO()
                picam2.capture_file(data, format='jpeg')
                if data.getvalue() == b"":
                    self.send_error(404, "Image Not Found")
                    return
                    
                self.send_response(200)
                self.wfile.write(data.getvalue())
                
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
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
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (int(width), int(height))}))
output = StreamingOutput()
picam2.start_recording(JpegEncoder(), FileOutput(output))

try:
    port = int(get_env_var("PORT", 8000));
    address = ('', port)
    server = StreamingServer(address, StreamingHandler)
    if (get_env_var("KEYFILE", False)):
        server.socket = ssl.wrap_socket(
                server.socket,
                keyfile=get_env_var("KEYFILE"),
                certfile=get_env_var("CERTFILE"),
                server_side=True)
    print(f"Starting picamera streamer on port {port}")
    server.serve_forever()
finally:
    picam2.stop_recording()
