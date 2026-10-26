"""Load seed resources (e.g. facility Organizations) onto the FHIR server.

    python tools/seed_fhir.py                          # seed/organizations.json -> $FHIR_BASE_URL
    python tools/seed_fhir.py --base http://localhost:8080/fhir seed/organizations.json
    python tools/seed_fhir.py --transaction            # POST the file as one FHIR transaction instead

The seed file is a FHIR transaction Bundle. By default each entry is sent separately as a
conditional update (PUT Type?identifier=system|value), which works on any FHIR server and
re-running it updates rather than duplicates. Simulated data only.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from siu2fhir_au.fhir_client import FhirClient, FhirError   # noqa: E402
from siu2fhir_au.mapping import _search                     # noqa: E402


def seed(client: FhirClient, bundle: dict) -> list[str]:
    done = []
    for entry in bundle.get("entry", []):
        res, req = entry["resource"], entry.get("request", {})
        rtype, _, query = req.get("url", res["resourceType"]).partition("?")
        ident = urllib.parse.parse_qs(query).get("identifier", [""])[0]
        if req.get("method") != "PUT" or "|" not in ident:
            raise SystemExit(f"Entry for {rtype} must be 'PUT {rtype}?identifier=system|value'")
        system, value = ident.split("|", 1)
        ref = client.conditional_update(rtype, _search(system, value), res)
        done.append(f"{ref}  ({system}|{value})")
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", default=[str(ROOT / "seed" / "organizations.json")])
    ap.add_argument("--base", default=os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir"))
    ap.add_argument("--transaction", action="store_true", help="POST each file as a FHIR transaction")
    args = ap.parse_args()
    client = FhirClient(args.base)
    for path in args.files:
        bundle = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        try:
            if args.transaction:
                _, _, resp = client._request("POST", "", bundle)
                print(f"{path}: transaction {resp.get('type', '?')} with {len(resp.get('entry', []))} entries")
            else:
                for line in seed(client, bundle):
                    print(f"{path}: {line}")
        except FhirError as e:
            print(f"{path}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
