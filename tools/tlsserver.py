"""
An HTTPS server that one silent client cannot freeze (22 Oct 2026).

The streamer used to wrap its listening socket in TLS
(`server.socket = context.wrap_socket(server.socket, server_side=True)`). Then every
TLS handshake happens inside accept(), in the one thread that accepts connections,
with no time limit. A client that connects and never sends its TLS hello, which
internet scanners do all day, blocks that thread, and with it every other request:
the picture, /status, new stream viewers. The camera itself carries on. From outside
it looked like a camera that stalls about once a day (only Valleycam, the one
scanners find most), until health_check.sh restarted the service minutes later.
Reproduced on 22 Oct 2026: one idle TCP connection, and /status stopped answering.

Here the listening socket stays plain. Each connection is handed to its own thread
(ThreadingMixIn), and the handshake happens there, with a time limit: a silent client
holds up nobody but itself, and is dropped when its time runs out. After the handshake
each socket read or write gets its own time limit too, so a client that connects and
then says nothing cannot keep a thread for ever (the stream sets a limit of its own).
"""

import socketserver
import ssl
from http import server


class ThreadedTLSServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    # Set to an ssl.SSLContext to serve HTTPS; None serves plain HTTP.
    ssl_context = None
    # Seconds a client gets to complete its TLS handshake.
    handshake_timeout = 10.0
    # Seconds any one read or write may then wait on the client.
    request_timeout = 30.0

    def finish_request(self, request, client_address):
        if self.ssl_context is None:
            request.settimeout(self.request_timeout)
            return super().finish_request(request, client_address)
        request.settimeout(self.handshake_timeout)
        try:
            # On failure Python closes the half-made TLS socket itself.
            tls = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # never finished its hello, or not TLS at all: dropped, and nobody waited
        tls.settimeout(self.request_timeout)
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            self.shutdown_request(tls)
