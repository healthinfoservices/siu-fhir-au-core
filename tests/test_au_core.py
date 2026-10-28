"""Tests for the AU Core 2.0.0 rules (siu2fhir_au/au.py and the AU parts of mapping.py).

`AUCoreChecks` re-implements the AU Core / AU Base invariants this service must meet
in plain Python. It is a smoke test, NOT a substitute for the FHIR validator: run the
IG Publisher (or HAPI validation with the AU Core package) for real conformance.
"""
import os
import pathlib
import re
import sys
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from siu2fhir_au import au                                  # noqa: E402
from siu2fhir_au.config import Config                       # noqa: E402
from siu2fhir_au.hl7v2 import parse                         # noqa: E402
from siu2fhir_au.mapping import map_siu                     # noqa: E402
from siu2fhir_au.processor import Processor                 # noqa: E402
from fake_fhir import FakeFhir                              # noqa: E402

try:
    BNE = ZoneInfo("Australia/Brisbane")
except Exception as e:  # zoneinfo.ZoneInfoNotFoundError on Windows without tzdata
    raise ImportError("Time zone data not found - run: pip install -r requirements.txt "
                      "(installs tzdata, needed on Windows)") from e
BASE = "http://example.org/fhir/sid"
REG = au.Registry.load(str(ROOT / "config" / "au-registry.json"))
SAMPLES = sorted((ROOT / "samples").glob("*.hl7"))


def sample(name: str) -> str:
    return (ROOT / "samples" / name).read_bytes().decode()


def mapped(text: str, reg=REG):
    return map_siu(parse(text), BASE, BNE, reg)


def refs_for(m) -> dict:
    keys = ["patient"] + [x.key for x in m.practitioners + m.locations + m.organizations]
    return {k: f"Res/{k}" for k in keys}


def by_system(identifiers, system):
    return next((i for i in identifiers if i.get("system") == system), None)


class AUCoreChecks:
    """Python versions of the AU Core / AU Base constraints (error level)."""

    DAR = au.DAR_EXT

    @classmethod
    def problems(cls, res: dict) -> list[str]:
        rt, out = res["resourceType"], []
        has_dar = lambda e: any(x.get("url") == cls.DAR for x in e.get("extension", []))  # noqa: E731
        if rt == "Patient":
            if not any(i.get("system") and i.get("value") for i in res.get("identifier", [])):
                out.append("au-core-pat-01: no identifier with system and value")
            names = res.get("name", [])
            if not names:
                out.append("Patient.name 1..*")
            fam = any(n.get("family") for n in names)
            if fam == any(has_dar(n) for n in names):
                out.append("au-core-pat-02: family xor data-absent-reason")
            for n in names:
                if bool(n.get("text") or n.get("family") or n.get("given")) == has_dar(n):
                    out.append("au-core-pat-03: text/family/given xor data-absent-reason")
            if "gender" not in res:
                out.append("Patient.gender 1..1")
            if "birthDate" not in res and not has_dar(res.get("_birthDate", {})):
                out.append("Patient.birthDate 1..1")
            for i in res.get("identifier", []):
                if i.get("system") == au.SYS_IHI and au.hi_number_problem(i["value"], "800360", "IHI"):
                    out.append("AU IHI value invalid")
                if i.get("system") == au.SYS_MEDICARE and not re.fullmatch(r"[0-9]{10,11}", i["value"]):
                    out.append("AU Medicare length")
                if i.get("type", {}).get("coding", [{}])[0].get("code") in ("MR", "PI") and "assigner" in i:
                    if not i["assigner"].get("display"):
                        out.append("AU MRN/PI assigner.display 1..1")
            for a in res.get("address", []):
                if not (a.get("text") or a.get("line")):
                    out.append("inv-add-0")
        if rt == "Practitioner":
            if not res.get("name") or not all(n.get("family") for n in res["name"]):
                out.append("AU Core Practitioner name.family 1..1")
            for i in res.get("identifier", []):
                if i.get("system") == au.SYS_HPII and au.hi_number_problem(i["value"], "800361", "HPI-I"):
                    out.append("AU HPI-I value invalid")
        if rt == "Location":
            if not (res.get("address") or res.get("type") or any(
                    i.get("system") and i.get("value") for i in res.get("identifier", []))):
                out.append("au-core-loc-01")
        if rt == "Organization":
            if not res.get("name"):
                out.append("AU Core Organization.name 1..1")
            for a in res.get("address", []):
                if a.get("use") == "home":
                    out.append("org-2")
        if rt == "Appointment":
            if not ((res.get("start") and res.get("end")) or res["status"] in ("proposed", "cancelled", "waitlist")):
                out.append("app-3")
        return out


class IdentifierTests(unittest.TestCase):
    def test_national_systems_match_au_base_6(self):
        # Literal values from the AU Base 6.0.0 identifier profiles - not the constants under test.
        self.assertEqual(au.SYS_IHI, "http://ns.electronichealth.net.au/id/hi/ihi/1.0")
        self.assertEqual(au.SYS_MEDICARE, "http://ns.electronichealth.net.au/id/medicare-number")
        self.assertEqual(au.SYS_DVA, "http://ns.electronichealth.net.au/id/dva")
        self.assertEqual(au.SYS_HPII, "http://ns.electronichealth.net.au/id/hi/hpii/1.0")
        self.assertEqual(au.SYS_MEDICARE_PROVIDER, "http://ns.electronichealth.net.au/id/medicare-provider-number")
        self.assertEqual(au.AU_V2_0203, "http://terminology.hl7.org.au/CodeSystem/v2-0203")
        self.assertEqual(au.PROFILE["Patient"], "http://hl7.org.au/fhir/core/StructureDefinition/au-core-patient")

    def test_patient_national_and_local_identifiers(self):
        p = mapped(sample("01_s12_book.hl7")).patient.resource
        ihi = by_system(p["identifier"], au.SYS_IHI)
        self.assertEqual(ihi["value"], "8003609900001239")
        self.assertEqual(ihi["type"]["coding"][0], {"system": au.V2_0203, "code": "NI"})
        mc = by_system(p["identifier"], au.SYS_MEDICARE)
        self.assertEqual((mc["value"], mc["type"]["coding"][0]["code"]), ("29999999991", "MC"))
        mrn = by_system(p["identifier"], "http://example.org/fhir/sid/mrn/SIMHOSP")
        self.assertEqual(mrn, {"type": {"coding": [{"system": au.V2_0203, "code": "MR"}]},
                               "system": "http://example.org/fhir/sid/mrn/SIMHOSP", "value": "900001"})
        self.assertEqual(p["meta"]["profile"], [au.PROFILE["Patient"]])

    def test_invalid_ihi_dropped_but_patient_kept(self):
        m = mapped(sample("06_s12_missing_data.hl7"))
        self.assertIsNone(by_system(m.patient.resource["identifier"], au.SYS_IHI))
        self.assertTrue(any("fails the Luhn check" in w for w in m.warnings))
        self.assertEqual(m.patient.resource["identifier"][0]["value"], "900003")

    def test_ihi_format_rules(self):
        self.assertIsNone(au.hi_number_problem("8003609900001239", "800360", "IHI"))
        self.assertIn("16 digits", au.hi_number_problem("800360990000123", "800360", "IHI"))
        self.assertIn("start with", au.hi_number_problem("8003619900004562", "800360", "IHI"))
        self.assertIn("Luhn", au.hi_number_problem("8003609900001230", "800360", "IHI"))

    def test_no_usable_identifier_is_AE(self):
        msg = sample("01_s12_book.hl7").replace(
            "900001^^^SIMHOSP^MR~8003609900001239^^^AUSHIC^NI~29999999991^^^AUSHIC^MC", "123^^^AUSHIC^NI")
        with FakeFhir() as fhir:
            r = Processor(Config(fhir_base_url=fhir.base_url), registry=REG).process(msg)
        self.assertEqual(r.ack_code, "AE")
        self.assertIn("au-core-pat-01", r.error)

    def test_bad_medicare_dropped(self):
        msg = sample("01_s12_book.hl7").replace("29999999991^^^AUSHIC^MC", "12345^^^AUSHIC^MC")
        m = mapped(msg)
        self.assertIsNone(by_system(m.patient.resource["identifier"], au.SYS_MEDICARE))
        self.assertTrue(any("Medicare number" in w for w in m.warnings))

    def test_dva_kept_as_generic_identifier(self):
        msg = sample("01_s12_book.hl7").replace("^^^AUSHIC^MC", "^^^AUSDVA^DVA").replace("29999999991", "NBUR9080")
        m = mapped(msg)
        self.assertIsNone(by_system(m.patient.resource["identifier"], au.SYS_DVA))
        self.assertTrue(any("DVA number kept as a generic identifier" in w for w in m.warnings))

    def test_mrn_system_by_fixed_rule_without_assigner(self):
        msg = sample("01_s12_book.hl7").replace("900001^^^SIMHOSP^MR", "900001^^^OTHERHOSP^MR")
        mrn = mapped(msg, reg=au.Registry()).patient.resource["identifier"][0]
        self.assertEqual(mrn["system"], "http://example.org/fhir/sid/mrn/OTHERHOSP")
        self.assertNotIn("assigner", mrn)

    def test_mrn_without_authority_warns(self):
        m = mapped(sample("01_s12_book.hl7").replace("900001^^^SIMHOSP^MR", "900001^^^^MR"))
        self.assertEqual(m.patient.resource["identifier"][0]["system"], "http://example.org/fhir/sid/mrn/default")
        self.assertTrue(any("no assigning authority" in w for w in m.warnings))

    def test_practitioner_hpii_and_provider_number(self):
        m = mapped(sample("01_s12_book.hl7"))
        ident = m.practitioners[0].resource["identifier"][0]
        self.assertEqual((ident["system"], ident["value"]), (au.SYS_HPII, "8003619900004562"))
        self.assertEqual(ident["type"]["coding"][0]["code"], "NPI")
        m3 = mapped(sample("03_s14_modify.hl7"))
        ident = m3.practitioners[0].resource["identifier"][0]
        self.assertEqual(ident["system"], au.SYS_MEDICARE_PROVIDER)
        self.assertEqual(ident["type"]["coding"][0], {"system": au.AU_V2_0203, "code": "UPIN"})

    def test_invalid_hpii_kept_as_local(self):
        msg = sample("01_s12_book.hl7").replace("8003619900004562", "8003619900004560")
        m = mapped(msg)
        ident = m.practitioners[0].resource["identifier"][0]
        self.assertNotEqual(ident["system"], au.SYS_HPII)
        self.assertTrue(any("HPI-I" in w for w in m.warnings))


class MissingDataTests(unittest.TestCase):
    def setUp(self):
        self.m = mapped(sample("06_s12_missing_data.hl7"))
        self.p = self.m.patient.resource

    def test_gender_unknown_and_birthdate_absent_reason(self):
        self.assertEqual(self.p["gender"], "unknown")
        self.assertNotIn("birthDate", self.p)
        self.assertEqual(self.p["_birthDate"], {"extension": [{"url": au.DAR_EXT, "valueCode": "unknown"}]})

    def test_missing_family_name_gets_separate_absent_reason_name(self):
        self.assertEqual(self.p["name"][0]["given"], ["CHARLIE"])
        self.assertNotIn("extension", self.p["name"][0])
        self.assertEqual(self.p["name"][1], {"extension": [{"url": au.DAR_EXT, "valueCode": "unknown"}]})

    def test_empty_name(self):
        p = mapped(sample("06_s12_missing_data.hl7").replace("||^CHARLIE", "||")).patient.resource
        self.assertEqual(p["name"], [{"extension": [au.data_absent()]}])

    def test_practitioner_without_family_is_display_only(self):
        self.assertEqual(self.m.practitioners, [])
        appt = self.m.build_appointment(refs_for(self.m), None)
        disp = [x["actor"] for x in appt["participant"] if x["actor"].get("display") == "ANON"]
        self.assertEqual(disp, [{"display": "ANON"}])
        self.assertTrue(any("no family name" in w for w in self.m.warnings))


class DemographicsTests(unittest.TestCase):
    def test_address_normalised(self):
        msg = sample("01_s12_book.hl7").replace("^^BRISBANE^QLD^4000^AU", "^^BRISBANE^Queensland^4000^AUS")
        a = mapped(msg).patient.resource["address"][0]
        self.assertEqual((a["state"], a["country"]), ("QLD", "AU"))
        self.assertEqual(a["text"], "1 Example Street, BRISBANE, QLD 4000")

    def test_bad_postcode_warns(self):
        msg = sample("01_s12_book.hl7").replace("^QLD^4000^AU", "^QLD^40000^AU")
        m = mapped(msg)
        self.assertTrue(any("isn't 4 digits" in w for w in m.warnings))

    def test_indigenous_status_and_language(self):
        p = mapped(sample("01_s12_book.hl7")).patient.resource
        self.assertEqual(p["extension"], [{"url": au.EXT_INDIGENOUS,
                                           "valueCoding": {"system": au.CS_INDIGENOUS, "code": "4"}}])
        self.assertEqual(p["communication"][0]["language"],
                         {"text": "English", "coding": [{"system": "urn:ietf:bcp:47", "code": "en"}]})

    def test_indigenous_status_can_be_disabled(self):
        with mock.patch.dict(os.environ, {"INDIGENOUS_STATUS_FROM_PID10": "false"}):
            p = mapped(sample("01_s12_book.hl7")).patient.resource
        self.assertNotIn("extension", p)

    def test_unknown_indigenous_code_not_mapped(self):
        m = mapped(sample("01_s12_book.hl7").replace("|4^Neither", "|X^Neither"))
        self.assertNotIn("extension", m.patient.resource)
        self.assertTrue(any("PID-10" in w for w in m.warnings))


class LocationOrganizationTests(unittest.TestCase):
    def test_location_type_physical_type_and_placeholder_organization(self):
        reg = au.Registry(location_types={"CLIN": {"system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                                                   "code": "OF"}})
        m = mapped(sample("01_s12_book.hl7"), reg=reg)
        loc = m.locations[0]
        self.assertEqual(loc.resource["type"][0]["coding"][0]["code"], "OF")
        self.assertEqual(loc.resource["physicalType"]["coding"][0]["code"], "ro")
        self.assertEqual(loc.links, [("managingOrganization", "org-SIMHOSP")])
        org = m.organizations[0]
        self.assertEqual(org.mode, "lookup-or-create")
        self.assertEqual(org.resource["identifier"],
                         [{"system": "http://example.org/fhir/sid/organization", "value": "SIMHOSP"}])
        self.assertEqual(org.resource["meta"]["tag"][0]["code"], "placeholder")

    def test_untranslated_location_type_warns(self):
        m = mapped(sample("01_s12_book.hl7"), reg=au.Registry())
        self.assertEqual(m.locations[0].resource["type"][0]["coding"][0]["code"], "CLIN")
        self.assertTrue(any("AIL-4" in w for w in m.warnings))

    def test_participant_type_uses_v3_participation_type(self):
        m = mapped(sample("01_s12_book.hl7"))
        appt = m.build_appointment(refs_for(m), None)
        prac = next(x for x in appt["participant"] if x["actor"].get("reference", "").endswith("practitioner0"))
        self.assertEqual(prac["type"][0]["coding"][0], {"system": au.CS_V3_PARTICIPATION, "code": "ATND"})
        self.assertEqual(appt["meta"]["profile"][0].split("/")[-1], "siu-au-appointment")


class EndToEndAUTests(unittest.TestCase):
    def test_all_samples_meet_au_core_checks(self):
        with FakeFhir() as fhir:
            proc = Processor(Config(fhir_base_url=fhir.base_url), registry=REG)
            for path in SAMPLES:
                r = proc.process(path.read_bytes().decode())
                self.assertEqual(r.ack_code, "AA", f"{path.name}: {r.error}")
            for rtype in ("Patient", "Practitioner", "Location", "Organization", "Appointment"):
                for res in fhir.all(rtype):
                    with self.subTest(resource=f"{rtype}/{res['id']}"):
                        self.assertEqual(AUCoreChecks.problems(res), [])
            # SIMHOSP and SATELLITE (sample 05) - both placeholders here, as nothing was seeded
            self.assertEqual(sorted(o["identifier"][0]["value"] for o in fhir.all("Organization")),
                             ["SATELLITE", "SIMHOSP"])
            for loc in fhir.all("Location"):
                self.assertTrue(loc["managingOrganization"]["reference"].startswith("Organization/"))

    def test_checker_catches_violations(self):
        bad = {"resourceType": "Patient", "identifier": [{"value": "x"}], "name": [{"given": ["A"]}]}
        found = AUCoreChecks.problems(bad)
        for rule in ("au-core-pat-01", "au-core-pat-02", "Patient.gender", "Patient.birthDate"):
            self.assertTrue(any(rule in f for f in found), rule)


ORG_SYSTEM = "http://example.org/fhir/sid/organization"


class OrganizationLookupTests(unittest.TestCase):
    """Organizations come from the FHIR server; placeholders only for unknown facilities."""

    def seed(self, fhir):
        import json
        sys.path.insert(0, str(ROOT / "tools"))
        import seed_fhir
        from siu2fhir_au.fhir_client import FhirClient
        bundle = json.loads((ROOT / "seed" / "organizations.json").read_text())
        seed_fhir.seed(FhirClient(fhir.base_url), bundle)
        return fhir.all("Organization")[0]

    def test_existing_organization_is_used_and_never_overwritten(self):
        with FakeFhir() as fhir:
            seeded = self.seed(fhir)
            before = dict(seeded)
            proc = Processor(Config(fhir_base_url=fhir.base_url), registry=REG)
            for name in ("01_s12_book.hl7", "02_s13_reschedule.hl7"):
                self.assertEqual(proc.process(sample(name)).ack_code, "AA")
            orgs = fhir.all("Organization")
            self.assertEqual(len(orgs), 1)
            self.assertEqual(orgs[0], before)                         # untouched
            self.assertFalse([p for p in fhir.requests if p[0] in ("PUT", "POST") and "Organization" in p[1]][1:])
            loc = next(x for x in fhir.all("Location") if x["name"] == "Outpatient Clinic 1")
            self.assertEqual(loc["managingOrganization"],
                             {"reference": f"Organization/{seeded['id']}", "display": "Simulated Hospital"})
            self.assertEqual(loc["address"], seeded["address"][0])  # address copied from the Organization

    def test_missing_facility_gets_one_placeholder(self):
        with FakeFhir() as fhir:
            self.seed(fhir)
            proc = Processor(Config(fhir_base_url=fhir.base_url), registry=REG)
            r = proc.process(sample("05_s12_resource_timing.hl7"))          # facility SATELLITE
            self.assertEqual(r.ack_code, "AA", r.error)
            self.assertTrue(any("SATELLITE" in w and "placeholder" in w for w in r.warnings))
            self.assertEqual(proc.process(sample("05_s12_resource_timing.hl7")).ack_code, "AA")
            sat = [o for o in fhir.all("Organization") if o["identifier"][0]["value"] == "SATELLITE"]
            self.assertEqual(len(sat), 1)
            self.assertEqual(sat[0]["name"], "SATELLITE")
            self.assertEqual(sat[0]["meta"]["tag"][0]["code"], "placeholder")
            self.assertIn("If-None-Exist", fhir.posts[0][1])
            loc = next(x for x in fhir.all("Location") if x["name"] == "Physio Room 1")
            self.assertNotIn("address", loc)                            # placeholder has no address

    def test_curated_placeholder_is_not_overwritten(self):
        with FakeFhir() as fhir:
            proc = Processor(Config(fhir_base_url=fhir.base_url), registry=REG)
            proc.process(sample("05_s12_resource_timing.hl7"))
            org = fhir.all("Organization")[0]
            curated = dict(org, name="Satellite Clinic", meta={})                  # an admin edits it
            curated["address"] = [{"line": ["2 Edge St"], "city": "Ipswich", "state": "QLD",
                                   "postalCode": "4305", "country": "AU"}]
            fhir.store["Organization"][org["id"]] = curated
            r = proc.process(sample("05_s12_resource_timing.hl7").replace("MSG0005", "MSG0005B"))
            self.assertEqual(r.ack_code, "AA")
            self.assertEqual(fhir.all("Organization"), [curated])
            loc = fhir.all("Location")[0]
            self.assertEqual(loc["managingOrganization"]["display"], "Satellite Clinic")
            self.assertEqual(loc["address"]["city"], "Ipswich")

    def test_location_without_facility_has_no_organization(self):
        msg = sample("01_s12_book.hl7").replace("OPD^CLINIC1^^SIMHOSP^", "OPD^CLINIC1^^^")
        m = mapped(msg)
        self.assertEqual(m.organizations, [])
        self.assertEqual(m.locations[0].links, [])

    def test_organization_system_constant(self):
        from siu2fhir_au import mapping
        self.assertEqual(mapping.ORGANIZATION_ID_SYSTEM, ORG_SYSTEM)


class PatientPractitionerWriteModeTests(unittest.TestCase):
    """PATIENT_PRACTITIONER_WRITE_MODE: create-only (default) never changes an existing Patient or
    Practitioner on the server; upsert overwrites it with the SIU data (the original behaviour)."""

    def existing(self, fhir, item, rid, name):
        """Put a richer, curated resource on the server matching the SIU item's search identifier."""
        from urllib.parse import parse_qs
        from fake_fhir import _split_token
        system, value = _split_token(parse_qs(item.search)["identifier"][0])
        res = {"resourceType": item.resource_type, "id": rid,
               "identifier": [{"system": system, "value": value}],
               "name": [name], "telecom": [{"system": "email", "value": "curated@example.org"}]}
        fhir.store.setdefault(item.resource_type, {})[rid] = res
        return dict(res)

    def writes(self, fhir, rtype):
        return [r for r in fhir.requests if r[0] in ("PUT", "POST") and r[1].split("?")[0].endswith(rtype)]

    def test_default_is_create_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PATIENT_PRACTITIONER_WRITE_MODE", None)
            self.assertEqual(Config().patient_practitioner_write_mode, "create-only")

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            Config(patient_practitioner_write_mode="overwrite")

    def test_existing_patient_and_practitioner_not_overwritten(self):
        m = mapped(sample("01_s12_book.hl7"))
        with FakeFhir() as fhir:
            pat = self.existing(fhir, m.patient, "p-curated",
                                {"family": "Testpatient-Smith", "given": ["Alicia"]})
            prac = self.existing(fhir, m.practitioners[0], "d-curated",
                                 {"text": "Dr Jane Curated", "family": "Curated", "given": ["Jane"]})
            proc = Processor(Config(fhir_base_url=fhir.base_url), registry=REG)
            for name in ("01_s12_book.hl7", "02_s13_reschedule.hl7"):
                r = proc.process(sample(name))
                self.assertEqual(r.ack_code, "AA", r.error)
            self.assertEqual(fhir.all("Patient"), [pat])                  # unchanged, no duplicate
            self.assertIn(prac, fhir.all("Practitioner"))
            self.assertEqual(self.writes(fhir, "Patient"), [])
            self.assertEqual(r.resources["patient"], "Patient/p-curated")
            appt = fhir.get(r.appointment)
            actors = [p["actor"] for p in appt["participant"]]
            self.assertIn({"reference": "Patient/p-curated", "display": "Alicia Testpatient-Smith"}, actors)
            self.assertIn({"reference": "Practitioner/d-curated", "display": "Dr Jane Curated"}, actors)

    def test_missing_patient_and_practitioner_created_once(self):
        with FakeFhir() as fhir:
            proc = Processor(Config(fhir_base_url=fhir.base_url), registry=REG)
            for name in ("01_s12_book.hl7", "02_s13_reschedule.hl7"):
                self.assertEqual(proc.process(sample(name)).ack_code, "AA")
            self.assertEqual(len(fhir.all("Patient")), 1)
            pat_writes = self.writes(fhir, "Patient")
            self.assertEqual(len(pat_writes), 1)                          # created by message 1 only
            self.assertEqual(pat_writes[0][0], "POST")
            self.assertTrue(any(p[0].endswith("/Patient") and "If-None-Exist" in p[1] for p in fhir.posts))
            created = fhir.all("Patient")[0]
            self.assertEqual(created["name"], mapped(sample("01_s12_book.hl7")).patient.resource["name"])

    def test_upsert_mode_overwrites_existing(self):
        m = mapped(sample("01_s12_book.hl7"))
        with FakeFhir() as fhir:
            self.existing(fhir, m.patient, "p-curated", {"family": "Old", "given": ["Name"]})
            self.existing(fhir, m.practitioners[0], "d-curated", {"text": "Dr Old Name", "family": "Old"})
            cfg = Config(fhir_base_url=fhir.base_url, patient_practitioner_write_mode="upsert")
            r = Processor(cfg, registry=REG).process(sample("01_s12_book.hl7"))
            self.assertEqual(r.ack_code, "AA", r.error)
            pat = fhir.get("Patient/p-curated")
            self.assertEqual(pat["name"], m.patient.resource["name"])     # SIU data replaced it
            self.assertNotEqual(pat.get("telecom"), [{"system": "email", "value": "curated@example.org"}])
            self.assertEqual(fhir.get("Practitioner/d-curated")["name"], m.practitioners[0].resource["name"])
            self.assertTrue(any(w[0] == "PUT" for w in self.writes(fhir, "Patient")))

    def test_organization_still_never_overwritten_in_upsert_mode(self):
        with FakeFhir() as fhir:
            cfg = Config(fhir_base_url=fhir.base_url, patient_practitioner_write_mode="upsert")
            proc = Processor(cfg, registry=REG)
            proc.process(sample("05_s12_resource_timing.hl7"))
            org = fhir.all("Organization")[0]
            fhir.store["Organization"][org["id"]] = curated = dict(org, name="Curated")
            proc.process(sample("05_s12_resource_timing.hl7").replace("MSG0005", "MSG0005B"))
            self.assertEqual(fhir.all("Organization"), [curated])


if __name__ == "__main__":
    unittest.main()
