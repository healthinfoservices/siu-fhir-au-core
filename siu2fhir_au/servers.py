"""Network front ends: an MLLP listener and a small HTTP endpoint (stdlib only)."""
from __future__ import annotations

import json
import logging
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .processor import Processor

log = logging.getLogger("siu2fhir_au")

SB, EB, CR = b"\x0b", b"\x1c", b"\x0d"   # MLLP start block, end block, carriage return
MAX_MESSAGE_BYTES = 5 * 1024 * 1024


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def frame(text: str) -> bytes:
    return SB + text.encode("utf-8") + EB + CR


# ---------------------------------------------------------------------------
# MLLP
# ---------------------------------------------------------------------------
class _MLLPHandler(socketserver.BaseRequestHandler):
    processor: Processor  # set by make_mllp_server

    def handle(self) -> None:
        peer = "%s:%s" % self.client_address[:2]
        log.info("MLLP connection from %s", peer)
        buf = b""
        while True:
            chunk = self.request.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_MESSAGE_BYTES:
                log.error("MLLP message from %s exceeds %d bytes; closing", peer, MAX_MESSAGE_BYTES)
                return
            # A connection may carry many messages; process every complete frame.
            while True:
                start = buf.find(SB)
                end = buf.find(EB + CR, start + 1) if start >= 0 else -1
                if start < 0 or end < 0:
                    break
                payload, buf = buf[start + 1:end], buf[end + 2:]
                result = self.processor.process(decode(payload))
                self.request.sendall(frame(result.ack))
        log.info("MLLP connection from %s closed", peer)


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_mllp_server(host: str, port: int, processor: Processor) -> socketserver.TCPServer:
    handler = type("MLLPHandler", (_MLLPHandler,), {"processor": processor})
    return _ThreadingTCPServer((host, port), handler)


# ---------------------------------------------------------------------------
# HTTP:  POST /hl7  (body = raw HL7 message)   GET /health
# ---------------------------------------------------------------------------
class _HTTPHandler(BaseHTTPRequestHandler):
    processor: Processor

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/hl7":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_MESSAGE_BYTES:
            self._send(400, {"error": "body must be one HL7 message"})
            return
        result = self.processor.process(decode(self.rfile.read(length)))
        body = result.as_dict()
        body["ack"] = result.ack.replace("\r", "\n")   # readable in curl output
        self._send(200 if result.ack_code == "AA" else 422, body)

    def log_message(self, fmt: str, *args) -> None:
        log.debug("HTTP %s", fmt % args)


def make_http_server(host: str, port: int, processor: Processor) -> ThreadingHTTPServer:
    handler = type("HTTPHandler", (_HTTPHandler,), {"processor": processor})
    return ThreadingHTTPServer((host, port), handler)
