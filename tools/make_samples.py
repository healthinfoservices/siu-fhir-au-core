"""Generate simulated SIU S12/S13/S14/S15 messages (AU conventions) into samples/.

All patient, practitioner and location data here is fictitious. IHI, HPI-I and
Medicare values are SYNTHETIC: generated to pass the AU Base format checks
(prefix, length, Luhn) and not issued to anyone.
AU v2 conventions used (confirm with your sender): IHI = ^^^AUSHIC^NI,
Medicare = ^^^AUSHIC^MC, HPI-I = XCN.9 AUSHIC + XCN.13 NPI, Medicare provider
number = XCN.9 AUSHICPR, Indigenous status in PID-10.
Building segments from {field_number: value} avoids hand-counting pipes.

Scenario (appointment FIL2001 for patient TESTPATIENT, ALICE):
  01 S12  book    14 Oct 2026 09:30-10:00, Dr Jane SMITH, Outpatient Clinic 1
  02 S13  move to 15 Oct 2026 11:00-11:30 (patient request)
  03 S14  swap practitioner to Dr Raj JONES, add an interpreter note
  04 S15  cancel (patient cancelled)
  05 S12  a second patient booked using only resource-segment timing (AIS-4 + AIS-7/8)
          with no UTC offset, to exercise the default time zone.
  06 S12  missing data: no family name, birth date or sex; an IHI that fails the Luhn check.
"""
from __future__ import annotations

import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "samples"


def seg(name: str, fields: dict[int, str]) -> str:
    n = max(fields) if fields else 0
    if name == "MSH":
        # MSH-1 is the separator itself and MSH-2 the encoding characters.
        vals = [fields.get(i, "") for i in range(3, n + 1)]
        return "MSH|^~\\&|" + "|".join(vals)
    return name + "|" + "|".join(fields.get(i, "") for i in range(1, n + 1))


def msh(event: str, ctrl: str, ts: str) -> str:
    return seg("MSH", {3: "PAS", 4: "SIMHOSP", 5: "SIU2FHIR", 6: "POC", 7: ts,
                       9: f"SIU^{event}^SIU_S12", 10: ctrl, 11: "P", 12: "2.5"})


IHI_ALICE = "8003609900001239"          # synthetic, Luhn-valid
IHI_BAD = "8003609900001230"            # fails Luhn
MEDICARE_ALICE = "29999999991"          # synthetic, 11 digits (card number + IRN)
HPII_SMITH = "8003619900004562"         # synthetic, Luhn-valid

PID_ALICE = seg("PID", {1: "1", 3: f"900001^^^SIMHOSP^MR~{IHI_ALICE}^^^AUSHIC^NI~{MEDICARE_ALICE}^^^AUSHIC^MC",
                        5: "TESTPATIENT^ALICE^^^MS^^L", 7: "19800101", 8: "F", 10: "4^Neither Aboriginal nor Torres Strait Islander origin^AUSINDIGENOUS",
                        15: "en^English^ISO639",
                        11: "1 Example Street^^BRISBANE^QLD^4000^AU",
                        13: "^PRN^PH^^^00^00000000~^NET^Internet^alice@example.org"})
PID_BOB = seg("PID", {1: "1", 3: "900002^^^SIMHOSP^MR", 5: "TESTPATIENT^BOB^^^MR^^L",
                      7: "19751231", 8: "M"})

AIS_GP = seg("AIS", {1: "1", 2: "A", 3: "GPCONS^General consultation^LOCAL"})
AIL_CLINIC = seg("AIL", {1: "1", 2: "A", 3: "OPD^CLINIC1^^SIMHOSP^^^^^Outpatient Clinic 1",
                         4: "CLIN^Clinic^LOCAL"})
AIP_SMITH = seg("AIP", {1: "1", 2: "A", 3: f"{HPII_SMITH}^SMITH^JANE^^^DR^^^AUSHIC^^^^NPI",
                        4: "ATND^Attending^LOCAL"})
AIP_JONES = "2426621B^JONES^RAJ^^^DR^^^AUSHICPR"   # Medicare provider number (synthetic format example)


def sch(fields: dict[int, str]) -> str:
    base = {1: "PLC1001^PAS", 2: "FIL2001^SCHED"}
    base.update(fields)
    return seg("SCH", base)


MESSAGES = {
    "01_s12_book.hl7": [
        msh("S12", "MSG0001", "20261007090000+1000"),
        sch({7: "FOLLOWUP^Follow-up^HL70276", 8: "Normal^Normal^HL70277", 9: "30", 10: "min",
             11: "^^^20261014093000+1000^20261014100000+1000", 25: "Booked"}),
        PID_ALICE, "RGS|1|A", AIS_GP, AIL_CLINIC, AIP_SMITH,
    ],
    "02_s13_reschedule.hl7": [
        msh("S13", "MSG0002", "20261007091000+1000"),
        sch({6: "PATREQ^Patient request^LOCAL", 7: "FOLLOWUP^Follow-up^HL70276",
             9: "30", 10: "min", 11: "^^^20261015110000+1000^20261015113000+1000",
             25: "Booked"}),
        PID_ALICE, "RGS|1|U", AIS_GP, AIL_CLINIC, AIP_SMITH,
    ],
    "03_s14_modify.hl7": [
        msh("S14", "MSG0003", "20261007092000+1000"),
        sch({7: "FOLLOWUP^Follow-up^HL70276", 9: "30", 10: "min",
             11: "^^^20261015110000+1000^20261015113000+1000"}),   # no SCH-25: keep status
        "NTE|1||Interpreter required (Mandarin)",
        PID_ALICE, "RGS|1|U", AIS_GP, AIL_CLINIC,
        seg("AIP", {1: "1", 2: "D", 3: f"{HPII_SMITH}^SMITH^JANE^^^DR^^^AUSHIC^^^^NPI"}),
        seg("AIP", {1: "2", 2: "A", 3: AIP_JONES, 4: "ATND^Attending^LOCAL"}),
    ],
    "04_s15_cancel.hl7": [
        msh("S15", "MSG0004", "20261007093000+1000"),
        sch({6: "PATCANC^Patient cancelled^LOCAL", 7: "FOLLOWUP^Follow-up^HL70276",
             9: "30", 10: "min", 11: "^^^20261015110000+1000^20261015113000+1000",
             25: "Cancelled"}),
        PID_ALICE, "RGS|1|U", AIS_GP, AIL_CLINIC,
        seg("AIP", {1: "1", 2: "U", 3: AIP_JONES, 4: "ATND^Attending^LOCAL"}),
    ],
    "05_s12_resource_timing.hl7": [
        msh("S12", "MSG0005", "20261007094000+1000"),
        sch({1: "PLC1002^PAS", 2: "FIL2002^SCHED", 7: "ROUTINE^Routine^HL70276"}),
        PID_BOB, "RGS|1|A",
        seg("AIS", {1: "1", 2: "A", 3: "PHYSIO^Physiotherapy^LOCAL",
                    4: "20261016140000", 7: "45", 8: "min"}),
        seg("AIL", {1: "1", 2: "A", 3: "OPD^PHYSIO1^^SATELLITE^^^^^Physio Room 1"}),
    ],
    "06_s12_missing_data.hl7": [
        msh("S12", "MSG0006", "20261007095000+1000"),
        sch({1: "PLC1003^PAS", 2: "FIL2003^SCHED", 9: "15", 10: "min",
             11: "^^^20261017090000+1000^20261017091500+1000", 25: "Booked"}),
        seg("PID", {1: "1", 3: f"900003^^^SIMHOSP^MR~{IHI_BAD}^^^AUSHIC^NI", 5: "^CHARLIE"}),
        "RGS|1|A",
        seg("AIS", {1: "1", 2: "A", 3: "GPCONS^General consultation^LOCAL"}),
        seg("AIP", {1: "1", 2: "A", 3: "P9999^^ANON", 4: "ATND^Attending^LOCAL"}),
    ],
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, segs in MESSAGES.items():
        # HL7 segment terminator is CR; files keep \r so they're byte-accurate.
        (OUT / name).write_bytes("\r".join(segs).encode() + b"\r")
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
