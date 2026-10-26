"""Generate FSH example instances from the AU Core service's actual output.

Runs samples/*.hl7 through siu2fhir_au's Processor against the in-memory FHIR stand-in,
snapshots each Appointment after each message, then writes ig/input/fsh/examples.fsh.
Re-run after changing the mapping code, samples or config/au-registry.json:

    python3 ig/tools/gen_examples.py
"""
from __future__ import annotations

import copy
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fake_fhir import FakeFhir                                   # noqa: E402
from siu2fhir_au import au                                        # noqa: E402
from siu2fhir_au.config import Config                             # noqa: E402
from siu2fhir_au.mapping import EXT_SOURCE_MSG_DT, EXT_SOURCE_MSG_ID  # noqa: E402
from siu2fhir_au.processor import Processor                       # noqa: E402

OUT = ROOT / "ig" / "input" / "fsh" / "examples.fsh"

INSTANCE_OF = {"Appointment": "SIUAUAppointment", "Patient": "$AUCorePatient",
               "Practitioner": "$AUCorePractitioner", "Location": "$AUCoreLocation",
               "Organization": "$AUCoreOrganization"}
APPT_EXT_SLICE = {EXT_SOURCE_MSG_DT: "sourceMessageDateTime", EXT_SOURCE_MSG_ID: "sourceMessageControlId"}

CODE_KEYS = {"status", "gender", "use", "type", "required", "equivalence", "code", "valueCode"}  # scalar values only
DATE_KEYS = {"start", "end", "birthDate", "valueDateTime"}
CODE_PARENTS = {"telecom": {"system"}}

STEPS = [
    ("01_s12_book.hl7", "after-s12", "after the S12 new booking"),
    ("02_s13_reschedule.hl7", "after-s13", "after the S13 reschedule"),
    ("03_s14_modify.hl7", "after-s14", "after the S14 modification (practitioner change, note added)"),
    ("04_s15_cancel.hl7", "after-s15", "after the S15 cancellation"),
    ("05_s12_resource_timing.hl7", None, "booked by an S12 whose timing is only in the AIS segment"),
    ("06_s12_missing_data.hl7", None, "booked by an S12 with missing patient data (data-absent-reason)"),
]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def fsh_value(key: str, parent: str, value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if key in DATE_KEYS:
        return str(value)
    if key in CODE_KEYS or key in CODE_PARENTS.get(parent, set()) or (key == "system" and parent == "telecom"):
        return "#" + value if re.fullmatch(r"[A-Za-z0-9.\-_]+", value) else '#"' + value + '"'
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def rules(obj: dict, path: str = "", parent: str = "", top_type: str = "") -> list[str]:
    out = []
    for key, val in obj.items():
        if not path and key in ("resourceType", "id"):
            continue
        if not path and key == "meta":                 # keep tags; InstanceOf sets meta.profile
            for i, tag in enumerate(val.get("tag", [])):
                out += rules(tag, f"meta.tag[{i}]", "tag")
            continue
        if key.startswith("_"):                      # primitive extension, e.g. _birthDate
            elem = key[1:]
            p = f"{path}.{elem}" if path else elem
            for i, ext in enumerate(val.get("extension", [])):
                out += ext_rules(f"{p}.extension[{i}]", ext)
            continue
        if not path and key == "extension" and top_type == "Appointment":
            for ext in val:
                vkey = next(k for k in ext if k.startswith("value"))
                out.append(f"* extension[{APPT_EXT_SLICE[ext['url']]}].{vkey} = {fsh_value(vkey, 'extension', ext[vkey])}")
            continue
        p = f"{path}.{key}" if path else key
        if key == "extension":
            for i, ext in enumerate(val):
                out += ext_rules(f"{p}[{i}]", ext)
            continue
        if isinstance(val, dict):
            out += rules(val, p, key)
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    out += rules(item, f"{p}[{i}]", key)
                else:
                    out.append(f"* {p}[{i}] = {fsh_value(key, parent, item)}")
        else:
            out.append(f"* {p} = {fsh_value(key, parent, val)}")
    return out


def ext_rules(path: str, ext: dict) -> list[str]:
    out = [f'* {path}.url = "{ext["url"]}"']
    for k, v in ext.items():
        if k == "url":
            continue
        if isinstance(v, dict):
            out += rules(v, f"{path}.{k}", k)
        else:
            out.append(f"* {path}.{k} = {fsh_value(k, 'extension', v)}")
    return out


def instance(iid: str, res: dict, title: str, desc: str) -> str:
    head = [f"Instance: {iid}", f"InstanceOf: {INSTANCE_OF[res['resourceType']]}",
            f'Title: "{title}"', f'Description: "{desc}"', "Usage: #example"]
    return "\n".join(head + rules(res, top_type=res["resourceType"])) + "\n"


def main() -> None:
    registry = au.Registry.load(str(ROOT / "config" / "au-registry.json"))
    snapshots: list[tuple[str, str, dict]] = []
    with FakeFhir() as fhir:
        # Facilities known to the server before any SIU message arrives (seed/organizations.json).
        sys.path.insert(0, str(ROOT / "tools"))
        import json
        import seed_fhir
        from siu2fhir_au.fhir_client import FhirClient
        seed_fhir.seed(FhirClient(fhir.base_url), json.loads((ROOT / "seed" / "organizations.json").read_text()))
        proc = Processor(Config(fhir_base_url=fhir.base_url), registry=registry)
        for fname, suffix, desc in STEPS:
            r = proc.process((ROOT / "samples" / fname).read_bytes().decode())
            if r.ack_code != "AA":
                raise SystemExit(f"{fname}: {r.ack_code} {r.error}")
            snapshots.append((suffix, desc, copy.deepcopy(fhir.get(r.appointment))))
        others = {t: fhir.all(t) for t in ("Organization", "Patient", "Practitioner", "Location")}

    # Server ids -> stable instance ids from the first business identifier.
    idmap: dict[str, str] = {}
    for rtype, items in others.items():
        for res in items:
            idmap[f"{rtype}/{res['id']}"] = f"{rtype.lower()}-{slug(res['identifier'][0]['value'])}"

    def relink(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "reference" and isinstance(v, str) and v in idmap:
                    out[k] = f"{v.split('/')[0]}/{idmap[v]}"
                else:
                    out[k] = relink(v)
            return out
        if isinstance(obj, list):
            return [relink(x) for x in obj]
        return obj

    def label(res: dict) -> str:
        if res["resourceType"] in ("Location", "Organization"):
            return res.get("name", "")
        names = [n for n in res.get("name", []) if n.get("text")]
        return names[0]["text"] if names else "(name unknown)"

    blocks = ["// GENERATED by ig/tools/gen_examples.py from samples/*.hl7 - do not edit by hand.\n"
              "// Simulated data. IHI, HPI-I, HPI-O and Medicare values are synthetic.\n"
              "// organization-simhosp is seeded on the server (seed/organizations.json);\n"
              "// organization-satellite is a placeholder the service created for an unknown facility.\n"]
    for rtype in ("Organization", "Patient", "Practitioner", "Location"):
        for res in others[rtype]:
            blocks.append(instance(idmap[f"{rtype}/{res['id']}"], relink(res), f"{rtype}: {label(res)}",
                                   f"Simulated {rtype.lower()} created from the sample SIU messages."))
    for suffix, desc, appt in snapshots:
        ids = {i["type"]["coding"][0]["code"]: i["value"] for i in appt["identifier"]}
        fil = ids.get("FILL") or ids["PLAC"]
        iid = f"appointment-{slug(fil)}" + (f"-{suffix}" if suffix else "")
        title = f"Appointment {fil}" + (f" (after {suffix.split('-')[1].upper()})" if suffix else "")
        blocks.append(instance(iid, relink(appt), title, f"Appointment {fil} as stored {desc}."))
    OUT.write_text("\n".join(blocks))
    print(f"wrote {OUT} ({len(blocks) - 1} instances)")


if __name__ == "__main__":
    main()
