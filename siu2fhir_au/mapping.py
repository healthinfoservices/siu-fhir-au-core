"""Map HL7 v2 SIU S12/S13/S14/S15 messages to FHIR R4 resources conforming to AU Core 2.0.0.

Patient, Practitioner, Location and Organization are built to the AU Core profiles
(see au.py for the Australian rules). Appointment has no AU Core profile; it
conforms to this project's SIU AU Appointment profile.

This module is pure: it never talks to the network. `map_siu()` returns the
Patient / Practitioner / Location / Organization resources to write, and a function that
builds the Appointment once the server-side ids of those resources are known.

Field positions used (HL7 v2.5-style numbering):
  SCH-1  placer appointment ID (EI)      SCH-2  filler appointment ID (EI)
  SCH-6  event reason (CE)               SCH-7  appointment reason (CE, table 0276)
  SCH-9/10 duration + units
  SCH-11 appointment timing quantity (TQ; comp 4 = start, comp 5 = end)
  SCH-25 filler status code (CE, table 0278)
  PID-3 ids, PID-5 name, PID-7 DOB, PID-8 sex, PID-11 address, PID-13/14 phones
  AIS-3 service, AIS-4 start, AIS-7/8 duration
  AIG-3 resource, AIG-4 type, AIG-8 start, AIG-11/12 duration
  AIL-3 location (PL), AIL-6 start, AIL-9/10 duration
  AIP-3 personnel (XCN), AIP-4 role, AIP-6 start, AIP-9/10 duration
  PID-10 Indigenous status (AU convention), PID-15 primary language
  AIP-3.13 identifier type code (NPI = HPI-I)
  Resource segments with action code (field 2) 'D' are treated as removed.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Callable, Optional
from urllib.parse import quote

from . import au
from .hl7v2 import HL7ParseError, Message, Segment, parse_date, parse_dtm

SUPPORTED_EVENTS = {"S12", "S13", "S14", "S15"}
# Must match the IG's canonical (ig/sushi-config.yaml) - change both together.
IG_CANONICAL = os.getenv("IG_CANONICAL", "http://example.org/fhir/siu2fhir-au").rstrip("/")
EXT_SOURCE_MSG_DT = f"{IG_CANONICAL}/StructureDefinition/source-message-datetime"
EXT_SOURCE_MSG_ID = f"{IG_CANONICAL}/StructureDefinition/source-message-control-id"
APPOINTMENT_PROFILE = f"{IG_CANONICAL}/StructureDefinition/siu-au-appointment"
# MRN identifier systems are built as {MRN_SYSTEM_BASE}/{PID-3.4 assigning authority}.
MRN_SYSTEM_BASE = os.getenv("MRN_SYSTEM_BASE", "http://example.org/fhir/sid/mrn").rstrip("/")
# Facility (AIL-3.4) identifier system used to find Organizations on the FHIR server.
ORGANIZATION_ID_SYSTEM = os.getenv("ORGANIZATION_ID_SYSTEM", "http://example.org/fhir/sid/organization")
TAG_SYSTEM = f"{IG_CANONICAL}/CodeSystem/siu2fhir-tag"
SET_META_PROFILE = os.getenv("SET_META_PROFILE", "true").lower() in ("1", "true", "yes")
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
V2_0276 = "http://terminology.hl7.org/CodeSystem/v2-0276"

# HL7 table 0278 (filler status codes) -> FHIR R4 AppointmentStatus
FILLER_STATUS_MAP = {
    "pending": "pending",
    "waitlist": "waitlist",
    "booked": "booked",
    "started": "arrived",
    "complete": "fulfilled",
    "cancelled": "cancelled",
    "discontinued": "cancelled",  # v2.3+ code for discontinued
    "dc": "cancelled",            # v2.9+ code for discontinued
    "deleted": "entered-in-error",
    "blocked": "booked",        # no exact FHIR equivalent
    "overbook": "booked",
    "noshow": "noshow",
}

SEX_MAP = {"M": "male", "F": "female", "O": "other", "U": "unknown",
           "A": "other", "N": "unknown"}

# Statuses for which FHIR R4 invariant app-3 allows start/end to be absent.
STATUSES_WITHOUT_TIMES = {"proposed", "cancelled", "waitlist"}


class MappingError(ValueError):
    """The message is understood but cannot be turned into valid FHIR.

    err_code is the HL7 table 0357 code put in ERR-3 of the AE acknowledgement:
    101 = required field missing (default), 102 = data type error.
    """

    def __init__(self, message: str, err_code: str = "101"):
        super().__init__(message)
        self.err_code = err_code


@dataclass
class UpsertItem:
    """A resource to create-or-update, matched on one identifier."""
    key: str                      # local key used to wire up references
    resource_type: str
    search: str                   # e.g. "identifier=http://...|123"
    resource: dict
    # (element, key of another UpsertItem): filled with a Reference before upsert
    links: list = field(default_factory=list)
    # "upsert" = conditional update (Location);
    # "lookup-or-create" = use the server's copy unchanged, create only if missing
    # (Patient, Practitioner, Organization)
    mode: str = "upsert"


@dataclass
class MappedSIU:
    event: str
    control_id: str
    message_datetime: Optional[datetime]
    appointment_search: str
    patient: UpsertItem
    practitioners: list[UpsertItem]
    locations: list[UpsertItem]
    organizations: list[UpsertItem]
    # build_appointment(refs, existing_status, displays=None); displays: item key -> actor display
    build_appointment: Callable[..., dict]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sys(base: str, *parts: str) -> str:
    return "/".join([base.rstrip("/")] + [quote(p.strip() or "default", safe="") for p in parts])


def _search(system: str, value: str) -> str:
    # FHIR token search: identifier=system|value. Escape the token per FHIR rules
    # ('|' ',' '$' '\\' are escaped with a backslash), then URL-encode.
    def esc(s: str) -> str:
        return "".join("\\" + ch if ch in "|,$\\" else ch for ch in s)
    return "identifier=" + quote(f"{esc(system)}|{esc(value)}", safe="")


def _cc(seg: Segment, n: int, rep: int = 0) -> Optional[dict]:
    """CE/CWE -> CodeableConcept (code^text^coding-system)."""
    comps = seg.components(n, rep)
    if not comps or not any(comps):
        return None
    code = comps[0] if len(comps) > 0 else ""
    text = comps[1] if len(comps) > 1 else ""
    csys = comps[2] if len(comps) > 2 else ""
    cc: dict = {}
    if code:
        coding: dict = {"code": code}
        if csys.upper() == "HL70276":
            coding["system"] = V2_0276
        elif csys:
            # Unknown local coding system: keep it identifiable rather than guess.
            # Placeholder URI - replace with the real code system for your feed.
            coding["system"] = f"http://example.org/fhir/CodeSystem/v2-local/{quote(csys, safe='')}"
        if text:
            coding["display"] = text
        cc["coding"] = [coding]
    if text or code:
        cc["text"] = text or code
    return cc


def _profile(res: dict) -> dict:
    if SET_META_PROFILE:
        url = au.PROFILE.get(res["resourceType"]) or (
            APPOINTMENT_PROFILE if res["resourceType"] == "Appointment" else None)
        if url:
            res["meta"] = {"profile": [url]}
    return res


def _role(seg: Segment, n: int) -> Optional[dict]:
    """Participant role: known codes go to the system the participant-type value set uses."""
    known = au.participant_type(seg.component(n, 1), seg.component(n, 2))
    return known or _cc(seg, n)


def _active(segs: list[Segment]) -> list[Segment]:
    return [s for s in segs if s.value(2).upper() != "D"]


_UNIT_MINUTES = {
    "s": 1 / 60, "sec": 1 / 60, "second": 1 / 60, "seconds": 1 / 60,
    "min": 1, "mins": 1, "minute": 1, "minutes": 1,
    "h": 60, "hr": 60, "hrs": 60, "hour": 60, "hours": 60,
    "d": 1440, "day": 1440, "days": 1440,
}


def _duration(seg: Segment, n_val: int, n_units: int, warnings: list[str]) -> Optional[timedelta]:
    raw = seg.value(n_val).strip()
    if not raw:
        return None
    try:
        amount = float(raw)
    except ValueError:
        raise MappingError(f"{seg.name}-{n_val} duration {raw!r} is not numeric", err_code="102") from None
    if not math.isfinite(amount) or amount < 0:
        raise MappingError(f"{seg.name}-{n_val} duration {raw!r} must be a finite, non-negative number",
                           err_code="102")
    unit = seg.component(n_units, 1).strip().lower()
    if not unit:
        warnings.append(f"{seg.name}-{n_units} duration units empty; assumed minutes")
        unit = "min"
    if unit not in _UNIT_MINUTES:
        raise MappingError(f"{seg.name}-{n_units} duration unit {unit!r} not recognised", err_code="102")
    return timedelta(minutes=amount * _UNIT_MINUTES[unit])


# ---------------------------------------------------------------------------
# resource builders
# ---------------------------------------------------------------------------
def _patient_identifier(pid: Segment, i: int, base: str, reg: au.Registry,
                        warnings: list[str]) -> Optional[dict]:
    """One PID-3 repetition -> an AU Base identifier, or None if it must be dropped."""
    value = pid.component(3, 1, rep=i).strip()
    if not value:
        return None
    authority = pid.component(3, 4, rep=i, s=1) or pid.component(3, 4, rep=i)
    id_type = pid.component(3, 5, rep=i).strip().upper()
    where = f"PID-3[{i + 1}]"

    if id_type == "NI" or (authority.upper() == "AUSHIC" and value.startswith("800360")):
        problem = au.hi_number_problem(value, "800360", "IHI")
        if problem:
            warnings.append(f"{where}: {problem}; identifier dropped")
            return None
        return {"type": {"coding": [{"system": au.V2_0203, "code": "NI"}], "text": "IHI"},
                "system": au.SYS_IHI, "value": value}
    if id_type == "MC":
        if not re.fullmatch(r"[0-9]{10,11}", value):
            warnings.append(f"{where}: Medicare number {value!r} isn't 10 or 11 digits; identifier dropped")
            return None
        ident = {"type": {"coding": [{"system": au.V2_0203, "code": "MC"}], "text": "Medicare Number"},
                 "system": au.SYS_MEDICARE, "value": value}
        expiry = pid.component(3, 8, rep=i)
        if expiry:
            try:
                ident["period"] = {"end": parse_date(expiry)}
            except HL7ParseError:
                warnings.append(f"{where}: Medicare expiry {expiry!r} ignored (not a valid date)")
        return ident
    if authority.upper() == "AUSDVA":
        # AU DVA Number needs identifier.type from the DVA Entitlement value set, which
        # SIU doesn't carry - so it is kept as a generic identifier.
        warnings.append(f"{where}: DVA number kept as a generic identifier (no DVA entitlement type in SIU)")
    if id_type == "MR":
        # MRN namespace by fixed rule: {MRN_SYSTEM_BASE}/{PID-3.4}. No assigner is sent, so the
        # identifier is a plain Identifier (valid in AU Core Patient), not the AU MRN profile.
        if not authority:
            warnings.append(f"{where}: MRN has no assigning authority (PID-3.4); system ends in 'default'")
        return {"type": {"coding": [{"system": au.V2_0203, "code": "MR"}]},
                "system": _sys(MRN_SYSTEM_BASE, authority), "value": value}
    # PI / anything else: {base}/patient/{CX.4}/{CX.5}
    ident = {"system": _sys(base, "patient", authority, id_type or "id"), "value": value}
    if id_type:
        ident["type"] = {"coding": [{"system": au.V2_0203, "code": id_type}]}
    return ident


def _patient(pid: Segment, base: str, reg: au.Registry, warnings: list[str]) -> UpsertItem:
    identifiers = [x for x in (_patient_identifier(pid, i, base, reg, warnings)
                               for i, _ in enumerate(pid.repetitions(3))) if x]
    if not identifiers:
        raise MappingError("PID-3 has no usable patient identifier (AU Core au-core-pat-01)")

    res: dict = {"resourceType": "Patient", "identifier": identifiers}

    names = []
    for i, _ in enumerate(pid.repetitions(5)):
        family = pid.component(5, 1, rep=i, s=1) or pid.component(5, 1, rep=i)
        given = [g for g in (pid.component(5, 2, rep=i), pid.component(5, 3, rep=i)) if g]
        if not family and not given:
            continue
        name: dict = {}
        if pid.component(5, 7, rep=i).upper() == "L":
            name["use"] = "official"
        prefix, suffix = pid.component(5, 5, rep=i), pid.component(5, 4, rep=i)
        name["text"] = " ".join(x for x in [prefix, *given, family, suffix] if x)
        if family:
            name["family"] = family
        if given:
            name["given"] = given
        if prefix:
            name["prefix"] = [prefix]
        if suffix:
            name["suffix"] = [suffix]
        names.append(name)
    # au-core-pat-02: a family name xor a data-absent-reason on name. au-core-pat-03 forbids
    # data-absent-reason on a name that has text/family/given, so it goes on its own name entry.
    if not any("family" in n for n in names):
        warnings.append("PID-5: no family name; data-absent-reason added (AU Core au-core-pat-02)")
        names.append({"extension": [au.data_absent()]})
    res["name"] = names

    # Mandatory in AU Core: gender and birthDate (1..1)
    sex = pid.value(8).upper()
    res["gender"] = SEX_MAP.get(sex, "unknown") if sex else "unknown"
    try:
        dob = parse_date(pid.value(7))
    except HL7ParseError as e:
        raise MappingError(f"PID-7: {e}", err_code="102") from None
    if dob:
        res["birthDate"] = dob
    else:
        res["_birthDate"] = {"extension": [au.data_absent()]}

    addrs = []
    for i, _ in enumerate(pid.repetitions(11)):
        line = [x for x in (pid.component(11, 1, rep=i, s=1) or pid.component(11, 1, rep=i),
                            pid.component(11, 2, rep=i)) if x]
        a = au.au_address(line, pid.component(11, 3, rep=i), pid.component(11, 4, rep=i),
                          pid.component(11, 5, rep=i), pid.component(11, 6, rep=i),
                          warnings, f"PID-11[{i + 1}]")
        if a:
            addrs.append(a)
    if addrs:
        res["address"] = addrs

    telecom = []
    for n, use in ((13, "home"), (14, "work")):
        for i, _ in enumerate(pid.repetitions(n)):
            equip = pid.component(n, 3, rep=i).upper()
            email = pid.component(n, 4, rep=i)
            if email and (equip in ("INTERNET", "X.400") or pid.component(n, 2, rep=i).upper() == "NET"):
                telecom.append({"system": "email", "value": email, "use": use})
                continue
            number = pid.component(n, 1, rep=i)
            if not number:
                number = " ".join(x for x in (pid.component(n, 6, rep=i),
                                              pid.component(n, 7, rep=i)) if x)
            if number:
                tp = {"system": "phone", "value": number, "use": use}
                if equip == "CP":
                    tp["use"] = "mobile"
                telecom.append(tp)
    if telecom:
        res["telecom"] = telecom

    # Indigenous status: AU v2 convention carries it in PID-10 (VERIFY with the sender).
    if os.getenv("INDIGENOUS_STATUS_FROM_PID10", "true").lower() in ("1", "true", "yes"):
        code = pid.component(10, 1).strip()
        if code in au.INDIGENOUS_CODES:
            res["extension"] = [{"url": au.EXT_INDIGENOUS,
                                 "valueCoding": {"system": au.CS_INDIGENOUS, "code": code}}]
        elif code:
            warnings.append(f"PID-10: {code!r} isn't an Indigenous status code (1, 2, 3, 4, 9); not mapped")

    # Language (PID-15) -> communication.language (Must Support)
    lang_code, lang_text, lang_sys = (pid.component(15, 1), pid.component(15, 2),
                                      pid.component(15, 3).upper().replace(" ", ""))
    if lang_code or lang_text:
        lang: dict = {"text": lang_text or lang_code}
        if lang_code and lang_sys in ("ISO639", "ISO639-1", "BCP47", "IETF"):
            lang["coding"] = [{"system": "urn:ietf:bcp:47", "code": lang_code.lower()}]
        res["communication"] = [{"language": lang}]

    primary = identifiers[0]
    # An existing Patient on the server is used as is (it is likely richer / more accurate);
    # this one is only created when no Patient has the primary identifier.
    return UpsertItem("patient", "Patient", _search(primary["system"], primary["value"]), _profile(res),
                      mode="lookup-or-create")


def _practitioner(aip: Segment, idx: int, base: str, warnings: list[str]) -> tuple[Optional[UpsertItem], dict]:
    """Returns (upsert item or None, participant stub)."""
    pid_val = aip.component(3, 1).strip()
    family = aip.component(3, 2, s=1) or aip.component(3, 2)
    given = aip.component(3, 3)
    prefix = aip.component(3, 6)
    display = " ".join(x for x in (prefix, given, family) if x) or pid_val
    participant: dict = {"status": "accepted"}
    role = _role(aip, 4)
    if role:
        participant["type"] = [role]
    if not pid_val:
        participant["actor"] = {"display": display or "Unidentified personnel"}
        return None, participant
    if not family:
        # AU Core Practitioner requires name.family (1..1).
        warnings.append(f"AIP-3 {pid_val!r}: no family name, so no AU Core Practitioner created; "
                        "display-only participant used")
        participant["actor"] = {"display": display}
        return None, participant

    authority = aip.component(3, 9, s=1) or aip.component(3, 9)
    id_type = aip.component(3, 13).strip().upper()
    ident: dict
    if id_type == "NPI" or (authority.upper() == "AUSHIC" and pid_val.startswith("800361")):
        problem = au.hi_number_problem(pid_val, "800361", "HPI-I")
        if problem:
            warnings.append(f"AIP-3: {problem}; kept as a local identifier")
            ident = {"system": _sys(base, "practitioner", authority), "value": pid_val}
        else:
            ident = {"type": {"coding": [{"system": au.V2_0203, "code": "NPI"}], "text": "HPI-I"},
                     "system": au.SYS_HPII, "value": pid_val}
    elif authority.upper() == "AUSHICPR":
        ident = {"type": {"coding": [{"system": au.AU_V2_0203, "code": "UPIN"}],
                          "text": "Medicare Provider Number"},
                 "system": au.SYS_MEDICARE_PROVIDER, "value": pid_val}
    else:
        ident = {"system": _sys(base, "practitioner", authority), "value": pid_val}

    name: dict = {"family": family, "text": display}
    if given:
        name["given"] = [given]
    if prefix:
        name["prefix"] = [prefix]
    res: dict = {"resourceType": "Practitioner", "identifier": [ident], "name": [name]}
    key = f"practitioner{idx}"
    participant["_ref"] = key
    participant["_display"] = display
    # As for Patient: an existing Practitioner is used as is; create only if missing.
    return (UpsertItem(key, "Practitioner", _search(ident["system"], pid_val), _profile(res),
                       mode="lookup-or-create"), participant)


def _organization(facility: str) -> UpsertItem:
    """Placeholder AU Core Organization for a facility code (AIL-3.4).

    The processor first looks the facility up on the FHIR server by
    ORGANIZATION_ID_SYSTEM|facility and uses the server's Organization unchanged.
    This placeholder is only created (with a 'placeholder' tag) when none exists.
    """
    res: dict = {"resourceType": "Organization",
                 "identifier": [{"system": ORGANIZATION_ID_SYSTEM, "value": facility}],
                 "name": facility, "active": True}
    _profile(res)
    res.setdefault("meta", {})["tag"] = [{"system": TAG_SYSTEM, "code": "placeholder",
                                          "display": "Placeholder created from an SIU message - needs curation"}]
    return UpsertItem(f"org-{facility}", "Organization", _search(ORGANIZATION_ID_SYSTEM, facility), res,
                      mode="lookup-or-create")


def _location(ail: Segment, idx: int, base: str, reg: au.Registry,
              orgs: dict[str, UpsertItem], warnings: list[str]) -> tuple[Optional[UpsertItem], dict]:
    poc, room, bed = ail.component(3, 1), ail.component(3, 2), ail.component(3, 3)
    facility = ail.component(3, 4, s=1) or ail.component(3, 4)
    description = ail.component(3, 9)
    parts = [p for p in (facility, poc, room, bed) if p]
    participant: dict = {"status": "accepted"}
    if not parts:
        participant["actor"] = {"display": description or "Unidentified location"}
        return None, participant
    value = "/".join(parts)
    system = _sys(base, "location")
    res: dict = {"resourceType": "Location", "status": "active",
                 "identifier": [{"system": system, "value": value}],
                 "name": description or " ".join(parts)}
    code = ail.component(4, 1)
    if code and code in reg.location_types:
        res["type"] = [{"coding": [reg.location_types[code]], "text": ail.component(4, 2) or code}]
    else:
        loc_type = _cc(ail, 4)
        if loc_type:
            res["type"] = [loc_type]
            warnings.append(f"AIL-4 {code!r}: no translation to ServiceDeliveryLocationRoleType - AU Extended "
                            "in the registry; local code sent")
    pt = au.physical_type(poc, room, bed)
    if pt:
        res["physicalType"] = pt
    links = []
    if facility:
        if facility not in orgs:
            orgs[facility] = _organization(facility)
        links.append(("managingOrganization", orgs[facility].key))
    key = f"location{idx}"
    participant["_ref"] = key
    participant["_display"] = res["name"]
    return UpsertItem(key, "Location", _search(system, value), _profile(res), links), participant


def _appointment_identifiers(sch: Segment, base: str) -> list[dict]:
    out = []
    for n, kind in ((2, "filler"), (1, "placer")):
        val = sch.component(n, 1)
        if val:
            ns = sch.component(n, 2) or sch.component(n, 3)
            ident = {"system": _sys(base, "appointment", kind, ns), "value": val}
            if kind == "filler":
                ident["type"] = {"coding": [{"system": V2_0203, "code": "FILL"}]}
            else:
                ident["type"] = {"coding": [{"system": V2_0203, "code": "PLAC"}]}
            out.append(ident)
    return out


def _timing(msg: Message, sch: Segment, warnings: list[str],
            tz: tzinfo) -> tuple[Optional[datetime], Optional[datetime]]:
    def dtm(raw: str, where: str) -> Optional[datetime]:
        try:
            return parse_dtm(raw, tz)
        except HL7ParseError as e:
            raise MappingError(f"{where}: {e}", err_code="102") from None

    # 1) SCH-11 TQ: component 4 = start, 5 = end (each a TS; first sub-component is the DTM)
    start = dtm(sch.component(11, 4, s=1), "SCH-11.4")
    end = dtm(sch.component(11, 5, s=1), "SCH-11.5")

    # 2) Resource segments (v2.5+ moved timing here). (segment, start field, dur field, units field)
    spec = [("AIS", 4, 7, 8), ("AIG", 8, 11, 12), ("AIL", 6, 9, 10), ("AIP", 6, 9, 10)]
    res_windows: list[tuple[datetime, Optional[datetime]]] = []
    for name, f_start, f_dur, f_units in spec:
        for seg in _active(msg.all(name)):
            s = dtm(seg.component(f_start, 1), f"{name}-{f_start}")
            if s is None:
                continue
            d = _duration(seg, f_dur, f_units, warnings)
            res_windows.append((s, s + d if d else None))

    if start is None and res_windows:
        start = min(w[0] for w in res_windows)
    if end is None and start is not None:
        d = _duration(sch, 9, 10, warnings)
        if d:
            end = start + d
        else:
            ends = [w[1] for w in res_windows if w[1] is not None]
            if ends:
                end = max(ends)
    if start and end and end < start:
        raise MappingError("Appointment end is before start")
    return start, end


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def map_siu(msg: Message, base: str, tz: tzinfo, reg: Optional[au.Registry] = None) -> MappedSIU:
    reg = reg or au.Registry()
    if msg.message_type != "SIU":
        raise MappingError(f"Unsupported message type {msg.message_type!r}")
    event = msg.trigger_event
    if event not in SUPPORTED_EVENTS:
        raise MappingError(f"Unsupported SIU trigger event {event!r}")
    sch = msg.first("SCH")
    if sch is None:
        raise MappingError("SCH segment missing")
    pid = msg.first("PID")
    if pid is None:
        raise MappingError("PID segment missing")

    warnings: list[str] = []
    try:
        msg_dt = parse_dtm(msg.msh.component(7, 1), tz)
    except HL7ParseError:
        msg_dt = None
        warnings.append("MSH-7 unparseable; message ordering check disabled for this message")

    identifiers = _appointment_identifiers(sch, base)
    if not identifiers:
        raise MappingError("Neither SCH-2 (filler) nor SCH-1 (placer) appointment ID present")
    appt_search = _search(identifiers[0]["system"], identifiers[0]["value"])

    patient = _patient(pid, base, reg, warnings)

    practitioners, prac_parts = [], []
    for i, aip in enumerate(_active(msg.all("AIP"))):
        item, part = _practitioner(aip, i, base, warnings)
        if item:
            practitioners.append(item)
        prac_parts.append(part)

    locations, loc_parts = [], []
    orgs: dict[str, UpsertItem] = {}
    for i, ail in enumerate(_active(msg.all("AIL"))):
        item, part = _location(ail, i, base, reg, orgs, warnings)
        if item:
            locations.append(item)
        loc_parts.append(part)

    other_parts = []
    for aig in _active(msg.all("AIG")):
        text = aig.component(3, 2) or aig.component(3, 1)
        if text:
            p: dict = {"status": "accepted", "actor": {"display": text}}
            t = _role(aig, 4)
            if t:
                p["type"] = [t]
            other_parts.append(p)

    service_types = [cc for cc in (_cc(s, 3) for s in _active(msg.all("AIS"))) if cc]
    start, end = _timing(msg, sch, warnings, tz)
    filler_status = sch.component(25, 1).strip().lower()
    if filler_status and filler_status not in FILLER_STATUS_MAP:
        warnings.append(f"SCH-25 filler status {filler_status!r} not in table 0278; ignored")
    comments = [n.value(3) for n in msg.all("NTE") if n.value(3)]
    # SCH-7 "appointment reason" uses HL7 table 0276 (ROUTINE, WALKIN, CHECKUP,
    # FOLLOWUP, EMERGENCY) - the same v2 table FHIR R4 binds appointmentType to.
    # SCH-8 "appointment type" (table 0277: Normal/Tentative/Complete) has no
    # clean FHIR R4 home and is not mapped.
    appt_type = _cc(sch, 7)
    event_reason = _cc(sch, 6)

    def decide_status(existing_status: Optional[str]) -> str:
        if event == "S15":
            return "cancelled"
        if filler_status in FILLER_STATUS_MAP:
            return FILLER_STATUS_MAP[filler_status]
        if event == "S12":
            return "booked"
        return existing_status or "booked"   # S13/S14 without SCH-25 keep current status

    def build_appointment(refs: dict[str, str], existing_status: Optional[str],
                          displays: Optional[dict[str, str]] = None) -> dict:
        """displays: item key -> actor display taken from the server's copy of the resource,
        used instead of the SIU name when the resource already existed."""
        displays = displays or {}
        status = decide_status(existing_status)
        if (start is None or end is None) and status not in STATUSES_WITHOUT_TIMES:
            raise MappingError(
                "Cannot determine appointment start and end (SCH-11, SCH-9/10 or "
                "AIS/AIG/AIL/AIP start + duration); FHIR R4 requires both for status "
                f"{status!r}")

        def resolve(part: dict) -> dict:
            part = dict(part)
            key, disp = part.pop("_ref", None), part.pop("_display", None)
            disp = displays.get(key) or disp
            if key:
                part["actor"] = {"reference": refs[key]}
                if disp:
                    part["actor"]["display"] = disp
            return part

        patient_actor: dict = {"reference": refs["patient"]}
        pname = next((n for n in patient.resource["name"] if "text" in n), {})
        pdisplay = " ".join(pname.get("given", []) + ([pname["family"]] if pname.get("family") else []))
        pdisplay = displays.get("patient") or pdisplay
        if pdisplay:
            patient_actor["display"] = pdisplay
        participants = [{"actor": patient_actor, "required": "required", "status": "accepted"}]
        participants += [resolve(p) for p in prac_parts + loc_parts] + other_parts

        appt: dict = _profile({"resourceType": "Appointment", "identifier": identifiers,
                               "status": status, "participant": participants})
        ext = []
        if msg_dt:
            ext.append({"url": EXT_SOURCE_MSG_DT, "valueDateTime": msg_dt.isoformat()})
        if msg.control_id:
            ext.append({"url": EXT_SOURCE_MSG_ID, "valueString": msg.control_id})
        if ext:
            appt["extension"] = ext
        if status == "cancelled" and event_reason:
            appt["cancelationReason"] = event_reason   # R4 spelling (one 'l')
        if service_types:
            appt["serviceType"] = service_types
        if appt_type:
            appt["appointmentType"] = appt_type
        if start and end:
            appt["start"] = start.isoformat()
            appt["end"] = end.isoformat()
            appt["minutesDuration"] = int((end - start).total_seconds() // 60)
        if comments:
            appt["comment"] = "\n".join(comments)
        return appt

    return MappedSIU(event=event, control_id=msg.control_id, message_datetime=msg_dt,
                     appointment_search=appt_search, patient=patient,
                     practitioners=practitioners, locations=locations,
                     organizations=list(orgs.values()),
                     build_appointment=build_appointment, warnings=warnings)
