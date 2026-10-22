"""Run with: python3 -m unittest discover -s tests   (from the repo root; needs openssl for a test certificate)"""
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http import server

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.tlsserver import ThreadedTLSServer  # noqa: E402


class Hello(server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("openssl"), "needs openssl to make a test certificate")
class ThreadedTLSServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.cert = os.path.join(cls.dir, "cert.pem")
        cls.key = os.path.join(cls.dir, "key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-keyout", cls.key, "-out", cls.cert],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def setUp(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=self.cert, keyfile=self.key)
        self.server = ThreadedTLSServer(("127.0.0.1", 0), Hello)
        self.server.ssl_context = context
        self.server.handshake_timeout = 1.0
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = ssl.create_default_context(cafile=self.cert)
        self.idle = []

    def tearDown(self):
        for s in self.idle:
            s.close()
        self.server.shutdown()
        self.server.server_close()

    def get(self, timeout=3):
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as raw:
            with self.client.wrap_socket(raw, server_hostname="localhost") as tls:
                tls.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
                reply = b""
                while chunk := tls.recv(4096):
                    reply += chunk
        return reply

    def silent_client(self):
        """Connects and never says a word, as port scanners do."""
        s = socket.create_connection(("127.0.0.1", self.port))
        self.idle.append(s)
        return s

    def test_a_request_is_answered(self):
        self.assertTrue(self.get().endswith(b"ok"))

    def test_a_silent_client_does_not_hold_up_anyone_else(self):
        # The fault this server exists to fix: with the listening socket wrapped in TLS,
        # this second request waited until the silent client went away.
        self.silent_client()
        time.sleep(0.2)  # let the server accept it first
        started = time.monotonic()
        self.assertTrue(self.get(timeout=0.9).endswith(b"ok"))
        self.assertLess(time.monotonic() - started, 0.9, "answered before the silent client timed out")

    def test_many_silent_clients_do_not_either(self):
        for _ in range(20):
            self.silent_client()
        time.sleep(0.2)
        self.assertTrue(self.get(timeout=0.9).endswith(b"ok"))

    def test_a_silent_client_is_dropped_when_its_time_runs_out(self):
        s = self.silent_client()
        s.settimeout(3)
        started = time.monotonic()
        self.assertEqual(s.recv(1), b"", "the server closed the connection")
        self.assertLess(time.monotonic() - started, 2.5)

    def test_a_client_that_does_not_speak_tls_is_dropped_and_nobody_waits(self):
        s = self.silent_client()
        s.settimeout(3)
        s.sendall(b"GET / HTTP/1.0\r\n\r\n")
        try:
            s.recv(1024)
        except ConnectionResetError:
            pass
        self.assertTrue(self.get().endswith(b"ok"))

    def test_a_client_that_goes_quiet_after_its_handshake_is_dropped_too(self):
        self.server.request_timeout = 1.0
        raw = self.silent_client()
        tls = self.client.wrap_socket(raw, server_hostname="localhost")
        self.idle.append(tls)
        tls.settimeout(3)
        started = time.monotonic()
        self.assertEqual(tls.recv(1), b"")
        self.assertLess(time.monotonic() - started, 2.5)


class PlainHTTPTest(unittest.TestCase):
    def test_without_a_context_it_serves_plain_http(self):
        srv = ThreadedTLSServer(("127.0.0.1", 0), Hello)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with socket.create_connection(srv.server_address, timeout=3) as s:
                s.sendall(b"GET / HTTP/1.0\r\n\r\n")
                reply = b""
                while chunk := s.recv(4096):
                    reply += chunk
            self.assertTrue(reply.endswith(b"ok"))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
