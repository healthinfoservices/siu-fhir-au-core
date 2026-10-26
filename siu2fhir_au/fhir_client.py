"""Tiny FHIR REST client (stdlib only) for the operations this service needs.

Uses standard FHIR R4 REST interactions:
  * search:              GET  [base]/[type]?identifier=system|value
  * conditional update:  PUT  [base]/[type]?identifier=system|value
    (creates the resource when nothing matches, updates it when exactly one
    matches, and fails with 412 when several match)
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

FHIR_JSON = "application/fhir+json"


class FhirError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class FhirClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 headers: Optional[dict] = None) -> tuple[int, dict, dict]:
        data = json.dumps(body).encode() if body is not None else None
        url = f"{self.base}/{path}" if path else self.base
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", FHIR_JSON)
        if data is not None:
            req.add_header("Content-Type", FHIR_JSON)
            req.add_header("Prefer", "return=representation")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode() or "{}"
                return resp.status, dict(resp.headers), json.loads(raw)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            raise FhirError(f"{method} {path} -> HTTP {e.code}: {_outcome_text(text)}",
                            e.code, text) from None
        except urllib.error.URLError as e:
            raise FhirError(f"{method} {path} -> cannot reach FHIR server: {e.reason}") from None

    def search_one(self, resource_type: str, search: str) -> Optional[dict]:
        _, _, bundle = self._request("GET", f"{resource_type}?{search}")
        entries = [e.get("resource") for e in bundle.get("entry", [])
                   if e.get("resource", {}).get("resourceType") == resource_type]
        if len(entries) > 1:
            raise FhirError(f"{resource_type}?{search} matched {len(entries)} resources")
        return entries[0] if entries else None

    def conditional_update(self, resource_type: str, search: str, resource: dict) -> str:
        """Create-or-update. Returns the server's 'Type/id' for the resource."""
        status, headers, body = self._request("PUT", f"{resource_type}?{search}", resource)
        rid = body.get("id") if isinstance(body, dict) else None
        if not rid:
            loc = headers.get("Location") or headers.get("Content-Location") or ""
            # e.g. http://host/fhir/Patient/123/_history/1
            parts = loc.split("/_history")[0].rstrip("/").split("/")
            rid = parts[-1] if len(parts) >= 2 and parts[-2] == resource_type else None
        if not rid:
            raise FhirError(f"PUT {resource_type}?{search} returned HTTP {status} without an id")
        return f"{resource_type}/{rid}"

    def conditional_create(self, resource_type: str, search: str, resource: dict) -> dict:
        """Create only if nothing matches (POST + If-None-Exist). Returns the server's resource.

        Never modifies an existing match, so data curated on the server is kept.
        """
        _, headers, body = self._request("POST", resource_type, resource, {"If-None-Exist": search})
        if isinstance(body, dict) and body.get("resourceType") == resource_type and body.get("id"):
            return body
        found = self.search_one(resource_type, search)   # server returned no body for an existing match
        if not found:
            raise FhirError(f"POST {resource_type} (If-None-Exist: {search}) returned no resource")
        return found

    def update(self, resource_type: str, rid: str, resource: dict) -> str:
        resource = dict(resource, id=rid)
        self._request("PUT", f"{resource_type}/{rid}", resource)
        return f"{resource_type}/{rid}"


def _outcome_text(text: str) -> str:
    try:
        oo = json.loads(text)
        issues = oo.get("issue", [])
        msgs = [i.get("diagnostics") or i.get("details", {}).get("text", "") for i in issues]
        msgs = [m for m in msgs if m]
        if msgs:
            return "; ".join(msgs)[:500]
    except (ValueError, AttributeError):
        pass
    return text[:500]
