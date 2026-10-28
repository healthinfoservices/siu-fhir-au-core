"""Process one HL7 v2 SIU message end to end and build the HL7 ACK."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import au
from .config import Config
from .fhir_client import FhirClient, FhirError
from .hl7v2 import Delimiters, HL7ParseError, Message, format_dtm, parse
from .mapping import EXT_SOURCE_MSG_DT, SUPPORTED_EVENTS, MappingError, map_siu

log = logging.getLogger("siu2fhir_au")


@dataclass
class Result:
    ack_code: str                       # AA, AE or AR
    ack: str                            # full ACK message (segments joined with \r)
    control_id: str = ""
    event: str = ""
    appointment: Optional[str] = None   # e.g. "Appointment/123"
    status: Optional[str] = None
    resources: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], {}, "")}


def _esc(text: str, d: Delimiters) -> str:
    out = text.replace(d.escape, f"{d.escape}E{d.escape}")
    for ch, code in ((d.field, "F"), (d.component, "S"), (d.repetition, "R"), (d.subcomponent, "T")):
        out = out.replace(ch, f"{d.escape}{code}{d.escape}")
    return out.replace("\r", " ").replace("\n", " ")


def build_ack(msg: Optional[Message], code: str, cfg: Config,
              err_code: Optional[str] = None, err_text: str = "") -> str:
    d = msg.delims if msg else Delimiters()
    enc = f"{d.component}{d.repetition}{d.escape}{d.subcomponent}"
    now = format_dtm(datetime.now(cfg.default_tz))
    if msg:
        m = msg.msh
        send_app, send_fac = m.field(3), m.field(4)
        event, proc_id, version, ctrl = m.component(9, 2), m.field(11) or "P", m.field(12) or "2.5", m.field(10)
    else:
        send_app = send_fac = event = ctrl = ""
        proc_id, version = "P", "2.5"
    fs = d.field
    segs = [
        fs.join(["MSH", enc, cfg.receiving_app, cfg.receiving_facility, send_app, send_fac,
                 now, "", f"ACK{d.component}{event}{d.component}ACK",
                 uuid.uuid4().hex[:20], proc_id, version]),
        fs.join(["MSA", code, ctrl]),
    ]
    if err_code:
        # ERR-3 HL7 error code (table 0357), ERR-4 severity, ERR-8 user message
        names = {"200": "Unsupported message type", "201": "Unsupported event code",
                 "101": "Required field missing", "102": "Data type error",
                 "207": "Application internal error"}
        err3 = d.component.join([err_code, names.get(err_code, ""), "HL70357"])
        segs.append(fs.join(["ERR", "", "", err3, "E", "", "", "", _esc(err_text, d)]))
    return "\r".join(segs)


def _person_display(res: dict) -> str:
    """Actor display for an existing Patient / Practitioner, built the same way as for SIU data:
    Patient = given + family (falling back to name.text); Practitioner = name.text (falling back to
    prefix + given + family)."""
    names = res.get("name") or []
    name = next((n for n in names if n.get("use") in (None, "official", "usual")), names[0] if names else {})
    given = list(name.get("given", [])) + ([name["family"]] if name.get("family") else [])
    if res.get("resourceType") == "Patient":
        return " ".join(given) or name.get("text", "")
    return name.get("text") or " ".join(list(name.get("prefix", [])) + given)


class Processor:
    def __init__(self, cfg: Config, client: Optional[FhirClient] = None,
                 registry: Optional[au.Registry] = None):
        self.registry = registry if registry is not None else au.Registry.load()
        self.cfg = cfg
        self.client = client or FhirClient(cfg.fhir_base_url, cfg.fhir_timeout_s)
        # Serialise processing so MLLP and HTTP input can't race on the same appointment.
        self._lock = threading.Lock()

    def process(self, text: str) -> Result:
        with self._lock:
            return self._process(text)

    def _fail(self, msg, code, err_code, text, **kw) -> Result:
        log.warning("Rejected message (%s): %s", code, text)
        return Result(ack_code=code, ack=build_ack(msg, code, self.cfg, err_code, text),
                      error=text, **kw)

    def _process(self, text: str) -> Result:
        try:
            msg = parse(text)
        except HL7ParseError as e:
            return self._fail(None, "AR", "207", f"Unparseable HL7: {e}")

        ctrl, event = msg.control_id, msg.trigger_event
        if msg.message_type != "SIU":
            return self._fail(msg, "AR", "200", f"Message type {msg.message_type!r} not supported",
                              control_id=ctrl, event=event)
        if event not in SUPPORTED_EVENTS:
            return self._fail(msg, "AR", "201", f"SIU event {event!r} not supported",
                              control_id=ctrl, event=event)
        try:
            mapped = map_siu(msg, self.cfg.identifier_system_base, self.cfg.default_tz, self.registry)
            existing = self.client.search_one("Appointment", mapped.appointment_search)

            # Ordering guard: ignore a message older than the one already applied.
            if existing and mapped.message_datetime:
                prev = next((x.get("valueDateTime") for x in existing.get("extension", [])
                             if x.get("url") == EXT_SOURCE_MSG_DT), None)
                if prev and datetime.fromisoformat(prev) > mapped.message_datetime:
                    w = (f"Stale message ignored: MSH-7 {mapped.message_datetime.isoformat()} is "
                         f"older than last applied {prev}")
                    log.info("%s (%s)", w, ctrl)
                    return Result("AA", build_ack(msg, "AA", self.cfg), ctrl, event,
                                  appointment=f"Appointment/{existing['id']}",
                                  status=existing.get("status"),
                                  warnings=mapped.warnings + [w])

            refs: dict[str, str] = {}
            server_res: dict[str, dict] = {}
            displays: dict[str, str] = {}
            # Organizations first (Locations reference them), then Patient, Practitioners, Locations.
            # "lookup-or-create" items (Organization; Patient and Practitioner unless
            # PATIENT_PRACTITIONER_WRITE_MODE=upsert): an existing resource on the server is used
            # unchanged - it is likely richer or more accurate than the SIU data - and the
            # SIU-built resource is only created when none matches.
            # "upsert" items (Location): conditional update from the SIU data.
            for item in [*mapped.organizations, mapped.patient, *mapped.practitioners, *mapped.locations]:
                for element, key in item.links:
                    linked = server_res.get(key, {})
                    item.resource[element] = {"reference": refs[key]}
                    if linked.get("name"):
                        item.resource[element]["display"] = linked["name"]
                    # Location.address (0..1) from the managing Organization's first address
                    if (element == "managingOrganization" and "address" not in item.resource
                            and linked.get("address")):
                        item.resource["address"] = dict(linked["address"][0])
                mode = item.mode
                if (item.resource_type in ("Patient", "Practitioner")
                        and self.cfg.patient_practitioner_write_mode == "upsert"):
                    mode = "upsert"
                if mode == "lookup-or-create":
                    found = self.client.search_one(item.resource_type, item.search)
                    if found is None:
                        found = self.client.conditional_create(item.resource_type, item.search,
                                                               item.resource)
                        if item.resource_type == "Organization":
                            mapped.warnings.append(
                                f"Facility {item.resource['name']!r} not on the FHIR server; "
                                f"placeholder Organization/{found['id']} created")
                        else:
                            log.info("%s: created %s/%s from the SIU message",
                                     ctrl, item.resource_type, found["id"])
                    else:
                        log.info("%s: using existing %s/%s unchanged",
                                 ctrl, item.resource_type, found["id"])
                        if item.resource_type in ("Patient", "Practitioner"):
                            disp = _person_display(found)
                            if disp:
                                displays[item.key] = disp
                    refs[item.key] = f"{item.resource_type}/{found['id']}"
                    server_res[item.key] = found
                else:
                    refs[item.key] = self.client.conditional_update(
                        item.resource_type, item.search, item.resource)

            appt = mapped.build_appointment(refs, existing.get("status") if existing else None, displays)
            if existing:
                appt_ref = self.client.update("Appointment", existing["id"], appt)
            else:
                appt_ref = self.client.conditional_update("Appointment", mapped.appointment_search, appt)
        except MappingError as e:
            return self._fail(msg, "AE", e.err_code, str(e), control_id=ctrl, event=event)
        except FhirError as e:
            return self._fail(msg, "AE", "207", str(e), control_id=ctrl, event=event)
        except Exception as e:  # noqa: BLE001 - the sender must always get an ACK
            log.exception("Unexpected error processing %s", ctrl)
            return self._fail(msg, "AE", "207", f"Internal error: {type(e).__name__}: {e}",
                              control_id=ctrl, event=event)

        log.info("%s %s -> %s (%s)", event, ctrl, appt_ref, appt["status"])
        for w in mapped.warnings:
            log.warning("%s: %s", ctrl, w)
        return Result("AA", build_ack(msg, "AA", self.cfg), ctrl, event,
                      appointment=appt_ref, status=appt["status"], resources=refs,
                      warnings=mapped.warnings)
