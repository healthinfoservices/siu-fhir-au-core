This page lists what the service does differently to meet AU Core 2.0.0, compared with a plain FHIR R4 mapping of the same SIU messages.

### Missing data

AU Core requires some elements even when the source doesn't know the value. Coded elements use the value set's own `unknown` code; other elements carry the [data-absent-reason](http://hl7.org/fhir/R4/extension-data-absent-reason.html) extension with code `unknown`.

| Element | AU Core rule | When PID is missing it |
|---|---|---|
| `Patient.gender` | 1..1 | `unknown` |
| `Patient.birthDate` | 1..1 | `_birthDate` with data-absent-reason |
| `Patient.name` | 1..*, au-core-pat-02 (family name xor data-absent-reason), au-core-pat-03 | An extra name containing only data-absent-reason |
| `Patient.identifier` | au-core-pat-01 (at least one identifier with system and value) | Message rejected with `AE` |
| `Practitioner.name.family` | 1..1 | No Practitioner is created; the appointment gets a display-only participant |
{:.grid}

### National identifiers

IHI, Medicare card number, HPI-I and Medicare provider number are mapped to the AU Base identifier profiles, with their fixed systems and type codes.
IHI and HPI-I values are checked (16 digits, prefix, Luhn) and Medicare numbers must be 10 or 11 digits. A value failing its check is dropped (IHI, Medicare) or kept as a local identifier (HPI-I), with a warning, so that an invalid number never reaches the server under a national system.

MRNs (PID-3.5 `MR`) are sent as plain identifiers with the system `http://example.org/fhir/sid/mrn/` + PID-3.4 and no assigner, so they don't claim the AU Base Medical Record Number profile (which needs `assigner.display`). That is allowed by AU Core Patient.

The service recognises the national identifiers from Australian HL7 v2 conventions: IHI as `^^^AUSHIC^NI`, Medicare as `^^^AUSHIC^MC`, HPI-I as XCN.13 `NPI`, Medicare provider number as XCN.9 `AUSHICPR`. These conventions should be confirmed with the sending system (see [Open Issues](open-issues.html)).

### Must Support elements populated when known

| Element | Source |
|---|---|
| Patient `indigenousStatus` extension | PID-10 |
| `Patient.communication.language` | PID-15 |
| `Patient.name.text` | Built from PID-5 |
| `Patient.address` (Australian Address) | PID-11, normalised |
| `Location.type` | AIL-4, translated via the registry |
| `Location.physicalType` | Derived from AIL-3 (bed / room / point of care) |
| `Location.managingOrganization` → AU Core Organization | AIL-3.4 facility, looked up on the FHIR server (placeholder if missing) |
| `Location.address` | Copied from that Organization's first address |
{:.grid}

Must Support elements with no SIU v2.5 source (for example gender identity and pronouns) are left out, as AU Core's *populate-if-known* obligation allows.

### Appointment

There is no AU Core Appointment profile. [SIU AU Appointment](StructureDefinition-siu-au-appointment.html) constrains `participant.actor` to AU Core Patient, Practitioner, PractitionerRole and Location.
Known participant role codes (such as `ATND`) are sent with the `v3-ParticipationType` code system that the participant-type value set uses.
