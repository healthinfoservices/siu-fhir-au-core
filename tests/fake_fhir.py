"""In-memory stand-in for a FHIR R4 server, implementing only what the service uses:
search by identifier, conditional update (PUT Type?identifier=...), update by id.

It mimics the spec'd semantics, NOT HAPI's exact behaviour; it lets the tests
exercise the real HTTP code path without a running HAPI server.
"""
from __future__ import annotations

import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


def _split_token(token: str) -> tuple[str, str]:
    """Split 'system|value' honouring FHIR backslash escapes."""
    parts, cur, i = [], "", 0
    while i < len(token):
        ch = token[i]
        if ch == "\\" and i + 1 < len(token):
            cur += token[i + 1]
            i += 2
            continue
        if ch == "|":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])


class FakeFhir:
    def __init__(self):
        self.store: dict[str, dict[str, dict]] = {}
        self.requests: list[tuple[str, str]] = []
        self.posts: list[tuple[str, dict]] = []
        self._ids = itertools.count(1)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/fhir+json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _match(self, rtype, query):
                ident = parse_qs(query).get("identifier", [""])[0]
                system, value = _split_token(ident)
                return [r for r in outer.store.get(rtype, {}).values()
                        if any(i.get("system") == system and i.get("value") == value
                               for i in r.get("identifier", []))]

            def do_GET(self):
                outer.requests.append(("GET", self.path))
                u = urlsplit(self.path)
                rtype = u.path.strip("/").split("/")[-1]
                hits = self._match(rtype, u.query)
                self._send(200, {"resourceType": "Bundle", "type": "searchset",
                                 "total": len(hits),
                                 "entry": [{"resource": r} for r in hits]})

            def do_POST(self):
                outer.requests.append(("POST", self.path))
                outer.posts.append((self.path, dict(self.headers)))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                rtype = urlsplit(self.path).path.strip("/").split("/")[-1]
                cond = self.headers.get("If-None-Exist")
                if cond:
                    hits = self._match(rtype, cond)
                    if len(hits) > 1:
                        self._send(412, {"resourceType": "OperationOutcome",
                                         "issue": [{"diagnostics": "multiple matches"}]})
                        return
                    if hits:
                        self._send(200, hits[0])
                        return
                rid = str(next(outer._ids))
                body["id"] = rid
                outer.store.setdefault(rtype, {})[rid] = body
                self._send(201, body, {"Location": f"/fhir/{rtype}/{rid}/_history/1"})

            def do_PUT(self):
                outer.requests.append(("PUT", self.path))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                u = urlsplit(self.path)
                segs = u.path.strip("/").split("/")
                if u.query:                                  # conditional update
                    rtype = segs[-1]
                    hits = self._match(rtype, u.query)
                    if len(hits) > 1:
                        self._send(412, {"resourceType": "OperationOutcome",
                                         "issue": [{"diagnostics": "multiple matches"}]})
                        return
                    rid = hits[0]["id"] if hits else str(next(outer._ids))
                    created = not hits
                else:
                    rtype, rid = segs[-2], segs[-1]
                    created = rid not in outer.store.get(rtype, {})
                if body.get("resourceType") != rtype:
                    self._send(400, {"resourceType": "OperationOutcome",
                                     "issue": [{"diagnostics": "resourceType mismatch"}]})
                    return
                body["id"] = rid
                outer.store.setdefault(rtype, {})[rid] = body
                self._send(201 if created else 200, body,
                           {"Location": f"/fhir/{rtype}/{rid}/_history/1"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/fhir"
        self._t = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def all(self, rtype: str) -> list[dict]:
        return list(self.store.get(rtype, {}).values())

    def get(self, ref: str) -> dict:
        rtype, rid = ref.split("/")
        return self.store[rtype][rid]


__all__ = ["FakeFhir", "unquote"]
