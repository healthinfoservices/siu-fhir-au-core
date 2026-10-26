"""AU Core 2.0.0 / AU Base 6.0.0 rules used by the mapping.

Everything Australian-specific lives here so mapping.py stays readable:
national identifier systems and checks, missing-data handling, Australian
address normalisation, and the local registry (configuration) lookup.

Values marked VERIFY were not confirmed against the published AU Core / AU Base
pages when this was written - see README "Unverified items".
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# --- AU Core 2.0.0 profile canonicals (VERIFY: URL pattern) -------------------------
AU_CORE = "http://hl7.org.au/fhir/core/StructureDefinition/"
PROFILE = {
    "Patient": AU_CORE + "au-core-patient",
    "Practitioner": AU_CORE + "au-core-practitioner",
    "Location": AU_CORE + "au-core-location",
    "Organization": AU_CORE + "au-core-organization",
}

# --- identifier systems and type codes (verified against AU Base 6.0.0 profiles) ----
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
AU_V2_0203 = "http://terminology.hl7.org.au/CodeSystem/v2-0203"   # AU extension of 0203 (UPIN)
SYS_IHI = "http://ns.electronichealth.net.au/id/hi/ihi/1.0"
SYS_MEDICARE = "http://ns.electronichealth.net.au/id/medicare-number"
SYS_DVA = "http://ns.electronichealth.net.au/id/dva"
SYS_HPII = "http://ns.electronichealth.net.au/id/hi/hpii/1.0"
SYS_HPIO = "http://ns.electronichealth.net.au/id/hi/hpio/1.0"          # VERIFY (and the NOI type coding in mapping.py)
SYS_MEDICARE_PROVIDER = "http://ns.electronichealth.net.au/id/medicare-provider-number"

# --- other code systems ---------------------------------------------------------------
DAR_EXT = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"
EXT_INDIGENOUS = "http://hl7.org.au/fhir/StructureDefinition/indigenous-status"
CS_INDIGENOUS = "https://healthterminologies.gov.au/fhir/CodeSystem/australian-indigenous-status-1"
INDIGENOUS_CODES = {"1", "2", "3", "4", "9"}                            # VERIFY
CS_PHYSICAL_TYPE = "http://terminology.hl7.org/CodeSystem/location-physical-type"
CS_V3_PARTICIPATION = "http://terminology.hl7.org/CodeSystem/v3-ParticipationType"
CS_PARTICIPANT_TYPE = "http://terminology.hl7.org/CodeSystem/participant-type"
# Codes in the R4 encounter-participant-type value set (verified against the R4 expansion)
V3_PARTICIPATION_CODES = {"ADM", "ATND", "CALLBCK", "CON", "DIS", "ESC", "REF", "SPRF", "PPRF", "PART"}
PARTICIPANT_TYPE_CODES = {"translator", "emergency"}

# Australian States and Territories (VERIFY: the value set's exact code values)
AU_STATES = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}
AU_STATE_NAMES = {
    "AUSTRALIAN CAPITAL TERRITORY": "ACT", "NEW SOUTH WALES": "NSW", "NORTHERN TERRITORY": "NT",
    "QUEENSLAND": "QLD", "SOUTH AUSTRALIA": "SA", "TASMANIA": "TAS", "VICTORIA": "VIC",
    "WESTERN AUSTRALIA": "WA",
}
AU_COUNTRY_VALUES = {"AU", "AUS", "AUSTRALIA"}


def data_absent(code: str = "unknown") -> dict:
    return {"url": DAR_EXT, "valueCode": code}


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def hi_number_problem(value: str, prefix: str, label: str) -> Optional[str]:
    """Checks an IHI / HPI-I / HPI-O: 16 digits, given prefix, Luhn. Returns a problem or None."""
    if not re.fullmatch(r"[0-9]{16}", value):
        return f"{label} {value!r} is not exactly 16 digits"
    if not value.startswith(prefix):
        return f"{label} {value!r} does not start with {prefix}"
    if not luhn_ok(value):
        return f"{label} {value!r} fails the Luhn check"
    return None


# --- registry (local configuration) ----------------------------------------------------
@dataclass
class Registry:
    """Local knowledge SIU messages don't carry: AIL-4 location type code translations.

    Facilities are NOT here (Organizations are looked up on the FHIR server), and MRN systems are
    built by a fixed rule (mapping.MRN_SYSTEM_BASE).

    Loaded from a JSON file (AU_REGISTRY env var, default config/au-registry.json).
    """
    location_types: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Registry":
        path = path or os.getenv("AU_REGISTRY") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "au-registry.json")
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        strip = lambda m: {k: v for k, v in m.items() if not k.startswith("_")}  # noqa: E731
        return cls(location_types=strip(data.get("locationTypes", {})))


# --- address ---------------------------------------------------------------------------
def au_address(line: list[str], city: str, state: str, postcode: str, country: str,
               warnings: list[str], where: str) -> Optional[dict]:
    """Build an Address, shaped to satisfy AU Base AustralianAddress when it is Australian.

    AU Core allows Address OR AustralianAddress, so an address that can't meet the
    Australian profile is still sent (as a plain Address) with a warning.
    """
    country_u = country.strip().upper()
    is_au = country_u in AU_COUNTRY_VALUES or (not country_u and (
        state.strip().upper() in AU_STATES or state.strip().upper() in AU_STATE_NAMES))
    a: dict = {}
    if line:
        a["line"] = line
    if city:
        a["city"] = city
    if state:
        a["state"] = state
    if postcode:
        a["postalCode"] = postcode
    if country:
        a["country"] = country
    if not a:
        return None
    if is_au:
        st = state.strip().upper()
        if st in AU_STATE_NAMES:
            a["state"] = AU_STATE_NAMES[st]
        elif st in AU_STATES:
            a["state"] = st
        elif state:
            warnings.append(f"{where}: state {state!r} isn't an Australian state/territory code; "
                            "address sent as a plain Address")
        if country_u:
            a["country"] = "AU"
        if postcode and not re.fullmatch(r"[0-9]{4}", postcode.strip()):
            warnings.append(f"{where}: postcode {postcode!r} isn't 4 digits; address sent as a plain Address")
    # AustralianAddress inv-add-0: text or line. Always give a readable text.
    text = ", ".join(x for x in (" ".join(line), city, " ".join(p for p in (a.get("state", ""), postcode) if p)) if x)
    if text:
        a["text"] = text
    return a


# --- coded values ------------------------------------------------------------------------
def participant_type(code: str, display: str) -> Optional[dict]:
    """Map a known role code to the code system the participant-type value set expects."""
    if code.upper() in V3_PARTICIPATION_CODES:
        c = {"system": CS_V3_PARTICIPATION, "code": code.upper()}
    elif code.lower() in PARTICIPANT_TYPE_CODES:
        c = {"system": CS_PARTICIPANT_TYPE, "code": code.lower()}
    else:
        return None
    cc: dict = {"coding": [c]}
    if display:
        cc["text"] = display
    return cc


def physical_type(point_of_care: str, room: str, bed: str) -> Optional[dict]:
    """Most specific PL component present -> location-physical-type (VERIFY codes; ward is an assumption)."""
    for value, code, disp in ((bed, "bd", "Bed"), (room, "ro", "Room"), (point_of_care, "wa", "Ward")):
        if value:
            return {"coding": [{"system": CS_PHYSICAL_TYPE, "code": code, "display": disp}]}
    return None
