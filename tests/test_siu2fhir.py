import json
import pathlib
import socket
import sys
import threading
import unittest
import urllib.request
from datetime import timezone
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from siu2fhir_au.config import Config                       # noqa: E402
from siu2fhir_au.hl7v2 import parse, parse_dtm, unescape     # noqa: E402
from siu2fhir_au.mapping import map_siu                       # noqa: E402
from siu2fhir_au.processor import Processor                   # noqa: E402
from siu2fhir_au.servers import make_http_server, make_mllp_server  # noqa: E402
from fake_fhir import FakeFhir                             # noqa: E402
import send_mllp                                           # noqa: E402

SAMPLES = ROOT / "samples"
try:
    BNE = ZoneInfo("Australia/Brisbane")
except Exception as e:  # zoneinfo.ZoneInfoNotFoundError on Windows without tzdata
    raise ImportError("Time zone data not found - run: pip install -r requirements.txt "
                      "(installs tzdata, needed on Windows)") from e


def sample(name: str) -> str:
    return (SAMPLES / name).read_bytes().decode()


def cfg(base_url: str) -> Config:
    return Config(fhir_base_url=base_url, identifier_system_base="http://example.org/fhir/sid",
                  default_tz_name="Australia/Brisbane")


class ParserTests(unittest.TestCase):
    def test_msh_numbering_and_components(self):
        m = parse(sample("01_s12_book.hl7"))
        self.assertEqual(m.msh.field(1), "|")
        self.assertEqual(m.msh.field(2), "^~\\&")
        self.assertEqual(m.msh.value(3), "PAS")
        self.assertEqual((m.message_type, m.trigger_event, m.control_id), ("SIU", "S12", "MSG0001"))
        pid = m.first("PID")
        self.assertEqual(pid.component(3, 4), "SIMHOSP")
        self.assertEqual(pid.component(13, 4, rep=1), "alice@example.org")

    def test_escapes_and_line_endings(self):
        m = parse("MSH|^~\\&|A|B|C|D|20261007||SIU^S12|1|P|2.5\nNTE|1||a\\F\\b\\S\\c\\T\\d\\R\\e\\E\\f")
        self.assertEqual(m.first("NTE").value(3), "a|b^c&d~e\\f")
        self.assertEqual(unescape("x\\Z\\y", m.delims), "x\\Z\\y")   # unknown kept

    def test_dtm(self):
        self.assertEqual(parse_dtm("20261014093000+1000", timezone.utc).isoformat(),
                         "2026-10-14T09:30:00+10:00")
        self.assertEqual(parse_dtm("202610140930", BNE).isoformat(), "2026-10-14T09:30:00+10:00")
        self.assertEqual(parse_dtm("20261014093000.25-0500", BNE).isoformat(),
                         "2026-10-14T09:30:00.250000-05:00")
        self.assertIsNone(parse_dtm("", BNE))
        with self.assertRaises(ValueError):
            parse_dtm("2026-10-14", BNE)


class MappingTests(unittest.TestCase):
    def test_s12_mapping(self):
        mapped = map_siu(parse(sample("01_s12_book.hl7")), "http://example.org/fhir/sid", BNE)
        p = mapped.patient.resource
        self.assertEqual(p["identifier"][0]["value"], "900001")
        self.assertEqual(p["name"][0], {"use": "official", "text": "MS ALICE TESTPATIENT",
                                        "family": "TESTPATIENT", "given": ["ALICE"], "prefix": ["MS"]})
        self.assertEqual((p["birthDate"], p["gender"]), ("1980-01-01", "female"))
        self.assertIn({"system": "email", "value": "alice@example.org", "use": "home"}, p["telecom"])
        appt = mapped.build_appointment(
            {"patient": "Patient/1", "practitioner0": "Practitioner/2", "location0": "Location/3"}, None)
        self.assertEqual(appt["status"], "booked")
        self.assertEqual(appt["start"], "2026-10-14T09:30:00+10:00")
        self.assertEqual(appt["end"], "2026-10-14T10:00:00+10:00")
        self.assertEqual(appt["minutesDuration"], 30)
        self.assertEqual(appt["appointmentType"]["coding"][0]["system"],
                         "http://terminology.hl7.org/CodeSystem/v2-0276")
        refs = [pt["actor"].get("reference") for pt in appt["participant"]]
        self.assertEqual(refs, ["Patient/1", "Practitioner/2", "Location/3"])
        self.assertEqual(appt["identifier"][0]["value"], "FIL2001")

    def test_resource_segment_timing_and_default_tz(self):
        mapped = map_siu(parse(sample("05_s12_resource_timing.hl7")), "http://x", BNE)
        appt = mapped.build_appointment({"patient": "Patient/1", "location0": "Location/2"}, None)
        self.assertEqual(appt["start"], "2026-10-16T14:00:00+10:00")
        self.assertEqual(appt["end"], "2026-10-16T14:45:00+10:00")


class EndToEndTests(unittest.TestCase):
    def test_full_lifecycle_s12_s13_s14_s15(self):
        with FakeFhir() as fhir:
            proc = Processor(cfg(fhir.base_url))
            r1 = proc.process(sample("01_s12_book.hl7"))
            self.assertEqual(r1.ack_code, "AA", r1.error)
            self.assertIn("MSA|AA|MSG0001", r1.ack)

            r2 = proc.process(sample("02_s13_reschedule.hl7"))
            self.assertEqual(r2.appointment, r1.appointment)
            a = fhir.get(r2.appointment)
            self.assertEqual((a["start"], a["status"]), ("2026-10-15T11:00:00+10:00", "booked"))

            r3 = proc.process(sample("03_s14_modify.hl7"))
            a = fhir.get(r3.appointment)
            pracs = [p["actor"]["display"] for p in a["participant"]
                     if p["actor"].get("reference", "").startswith("Practitioner/")]
            self.assertEqual(pracs, ["DR RAJ JONES"])           # SMITH removed (AIP action D)
            self.assertEqual(a["comment"], "Interpreter required (Mandarin)")
            self.assertEqual(a["status"], "booked")             # no SCH-25 -> status kept

            r4 = proc.process(sample("04_s15_cancel.hl7"))
            a = fhir.get(r4.appointment)
            self.assertEqual(a["status"], "cancelled")
            self.assertEqual(a["cancelationReason"]["text"], "Patient cancelled")

            self.assertEqual(len(fhir.all("Appointment")), 1)
            self.assertEqual(len(fhir.all("Patient")), 1)
            self.assertEqual(len(fhir.all("Practitioner")), 2)
            self.assertEqual(len(fhir.all("Location")), 1)

            # Late replay of the original booking must not resurrect the appointment.
            r5 = proc.process(sample("01_s12_book.hl7"))
            self.assertEqual(r5.ack_code, "AA")
            self.assertTrue(any("Stale" in w for w in r5.warnings))
            self.assertEqual(fhir.get(r1.appointment)["status"], "cancelled")

    def test_replaying_same_message_is_idempotent(self):
        with FakeFhir() as fhir:
            proc = Processor(cfg(fhir.base_url))
            for _ in range(3):
                self.assertEqual(proc.process(sample("01_s12_book.hl7")).ack_code, "AA")
            self.assertEqual(len(fhir.all("Appointment")), 1)
            self.assertEqual(len(fhir.all("Patient")), 1)

    def test_rejections(self):
        with FakeFhir() as fhir:
            proc = Processor(cfg(fhir.base_url))
            r = proc.process("MSH|^~\\&|A|B|C|D|20261007||ADT^A01|X1|P|2.5\rPID|1||1")
            self.assertEqual(r.ack_code, "AR")
            self.assertIn("ERR|||200^Unsupported message type^HL70357|E", r.ack)
            r = proc.process("MSH|^~\\&|A|B|C|D|20261007||SIU^S26|X2|P|2.5\rSCH|1")
            self.assertIn("201^Unsupported event code", r.ack)
            r = proc.process("not hl7")
            self.assertEqual(r.ack_code, "AR")
            # Booked but no timing anywhere -> AE (FHIR R4 needs start/end)
            r = proc.process("MSH|^~\\&|A|B|C|D|20261007||SIU^S12|X3|P|2.5\r"
                             "SCH|P9|F9\rPID|1||123^^^H^MR||DOE^JO")
            self.assertEqual(r.ack_code, "AE")
            self.assertIn("start and end", r.error)
            self.assertEqual(fhir.all("Appointment"), [])

    def test_fhir_unreachable_gives_AE(self):
        proc = Processor(cfg("http://127.0.0.1:9/fhir"))
        r = proc.process(sample("01_s12_book.hl7"))
        self.assertEqual(r.ack_code, "AE")
        self.assertIn("207^Application internal error", r.ack)


class NetworkTests(unittest.TestCase):
    def _serve(self, server):
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_mllp_multiple_messages_one_connection(self):
        with FakeFhir() as fhir:
            port = self._serve(make_mllp_server("127.0.0.1", 0, Processor(cfg(fhir.base_url))))
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                payload = b"".join(b"\x0b" + sample(n).encode() + b"\x1c\x0d"
                                   for n in ("01_s12_book.hl7", "02_s13_reschedule.hl7"))
                s.sendall(payload)
                buf = b""
                while buf.count(b"\x1c\x0d") < 2:
                    buf += s.recv(65536)
            self.assertIn(b"MSA|AA|MSG0001", buf)
            self.assertIn(b"MSA|AA|MSG0002", buf)
            # and the CLI sender
            ack = send_mllp.send("127.0.0.1", port, sample("04_s15_cancel.hl7"))
            self.assertIn("MSA|AA|MSG0004", ack)

    def test_http_endpoint(self):
        with FakeFhir() as fhir:
            port = self._serve(make_http_server("127.0.0.1", 0, Processor(cfg(fhir.base_url))))
            req = urllib.request.Request(f"http://127.0.0.1:{port}/hl7",
                                         data=sample("01_s12_book.hl7").encode(), method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            self.assertEqual(body["ack_code"], "AA")
            self.assertTrue(body["appointment"].startswith("Appointment/"))


# HL7 v2 table 0278 codes, as published at https://hl7.org/fhir/R4/v2/0278/index.html
# ("Discontinued" added in v2.3, "DC" in v2.9).
TABLE_0278 = {"Blocked", "Booked", "Cancelled", "Complete", "DC", "Deleted", "Discontinued",
              "Noshow", "Overbook", "Pending", "Started", "Waitlist"}


def with_status(code: str, event: str = "S14") -> str:
    """The S15 sample re-sent as another event with a different SCH-25."""
    return (sample("04_s15_cancel.hl7").replace("|Cancelled\r", f"|{code}\r")
            .replace("SIU^S15", f"SIU^{event}").replace("|PATCANC^Patient cancelled^LOCAL|", "||"))


def with_birth_date(value: str) -> str:
    return sample("01_s12_book.hl7").replace("||19800101|F|", f"||{value}|F|")


class DefectRegressionTests(unittest.TestCase):
    """Regression tests for ISSUE-01, ISSUE-02 and ISSUE-04 in docs/SIU_to_FHIR_Mapping.xlsx."""

    # --- ISSUE-01: SCH-25 'Discontinued' -------------------------------------------
    def test_discontinued_filler_status_cancels_appointment(self):
        for code in ("Discontinued", "DC", "discontinued"):
            with self.subTest(code=code), FakeFhir() as fhir:
                proc = Processor(cfg(fhir.base_url))
                self.assertEqual(proc.process(sample("01_s12_book.hl7")).ack_code, "AA")
                r = proc.process(with_status(code))
                self.assertEqual(r.ack_code, "AA", r.error)
                self.assertEqual(r.event, "S14")
                self.assertEqual(r.status, "cancelled")
                self.assertEqual(fhir.get(r.appointment)["status"], "cancelled")
                self.assertFalse([w for w in r.warnings if "SCH-25" in w])

    def test_every_table_0278_code_is_recognised(self):
        from siu2fhir_au.mapping import FILLER_STATUS_MAP
        self.assertEqual({c.lower() for c in TABLE_0278}, set(FILLER_STATUS_MAP))

    # --- ISSUE-02: IG ConceptMap codes ---------------------------------------------
    def test_ig_conceptmap_matches_table_0278_and_service(self):
        import re
        from siu2fhir_au.mapping import FILLER_STATUS_MAP
        fsh = (ROOT / "ig" / "input" / "fsh" / "terminology.fsh").read_text()
        block = fsh.split("Instance: HL70278ToAppointmentStatus")[1].split("Instance:")[0]
        sources = dict(re.findall(r"element\[(\d+)\]\.code = #(\S+)", block))
        targets = dict(re.findall(r"element\[(\d+)\]\.target\[0\]\.code = #(\S+)", block))
        ig_map = {sources[i]: targets[i] for i in sources}
        self.assertEqual(set(ig_map), TABLE_0278, "ConceptMap source codes must be exactly table 0278")
        for code, target in ig_map.items():
            self.assertEqual(FILLER_STATUS_MAP[code.lower()], target, f"IG and service disagree on {code}")

    # --- ISSUE-04: PID-7 ---------------------------------------------------------------
    def test_valid_birth_dates_keep_precision(self):
        from siu2fhir_au.hl7v2 import parse_date
        for raw, expected in (("1980", "1980"), ("198006", "1980-06"), ("19800615", "1980-06-15"),
                              ("198006151230+1000", "1980-06-15"), ("", None)):
            with self.subTest(raw=raw):
                self.assertEqual(parse_date(raw), expected)

    def test_invalid_birth_date_returns_AE_and_writes_nothing(self):
        for bad in ("UNKNOWN", "1980-01-01", "19801301", "19800230", "1980011", "19800101x"):
            with self.subTest(bad=bad), FakeFhir() as fhir:
                r = Processor(cfg(fhir.base_url)).process(with_birth_date(bad))
                self.assertEqual(r.ack_code, "AE", r.error)
                self.assertIn("PID-7", r.error)
                self.assertIn("ERR|||102^Data type error^HL70357|E", r.ack)
                self.assertIn("MSA|AE|MSG0001", r.ack)
                self.assertEqual(fhir.all("Patient"), [])
                self.assertEqual(fhir.all("Appointment"), [])

    def test_invalid_birth_date_over_mllp_still_gets_ack(self):
        with FakeFhir() as fhir:
            server = make_mllp_server("127.0.0.1", 0, Processor(cfg(fhir.base_url)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            ack = send_mllp.send("127.0.0.1", server.server_address[1], with_birth_date("UNKNOWN"), timeout=10)
            self.assertIn("MSA|AE|MSG0001", ack)

    # --- same class of defect found while fixing ISSUE-04 ---------------------------
    def test_out_of_range_timestamp_returns_AE(self):
        msg = sample("01_s12_book.hl7").replace("20261014093000+1000^", "20261399093000+1000^")
        with FakeFhir() as fhir:
            r = Processor(cfg(fhir.base_url)).process(msg)
        self.assertEqual(r.ack_code, "AE")
        self.assertIn("SCH-11.4", r.error)
        self.assertIn("102^Data type error", r.ack)

    def test_bad_duration_returns_AE(self):
        for bad in ("nan", "-30", "inf"):
            msg = sample("05_s12_resource_timing.hl7").replace("|20261016140000|||45|min", f"|20261016140000|||{bad}|min")
            with self.subTest(bad=bad), FakeFhir() as fhir:
                r = Processor(cfg(fhir.base_url)).process(msg)
                self.assertEqual(r.ack_code, "AE")
                self.assertIn("AIS-7", r.error)

    def test_unexpected_error_still_returns_ack(self):
        class Boom:
            def search_one(self, *a):
                raise RuntimeError("simulated bug")
        r = Processor(cfg("http://unused"), client=Boom()).process(sample("01_s12_book.hl7"))
        self.assertEqual(r.ack_code, "AE")
        self.assertIn("207^Application internal error", r.ack)
        self.assertIn("simulated bug", r.error)


if __name__ == "__main__":
    unittest.main()
