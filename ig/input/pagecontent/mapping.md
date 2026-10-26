Field numbering follows HL7 v2.5. The service also accepts the older convention of carrying appointment timing in SCH-11.

### SCH, AIS, AIG, AIL, AIP and NTE → Appointment

Profile: [SIU AU Appointment](StructureDefinition-siu-au-appointment.html)

| HL7 v2 | FHIR Appointment | Notes |
|---|---|---|
| SCH-2 (EI) | `identifier` (type FILL) | Preferred match key. System: `{base}/appointment/filler/{SCH-2.2}` |
| SCH-1 (EI) | `identifier` (type PLAC) | Match key when SCH-2 is empty |
| SCH-25 | `status` | Via [HL70278ToAppointmentStatus](ConceptMap-HL70278ToAppointmentStatus.html); see the status rules below |
| SCH-6 | `cancelationReason` | Only when the status is `cancelled` |
| SCH-7 | `appointmentType` | SCH-7 uses HL7 table 0276, the table FHIR R4 binds `appointmentType` to |
| SCH-8 | not mapped | Table 0277 (Normal/Tentative/Complete) has no clear FHIR R4 element |
| SCH-11.4 | `start` | |
| SCH-11.5 | `end` | |
| SCH-9 / SCH-10 | `end` = `start` + duration | Used when SCH-11.5 is empty |
| AIS-3 | `serviceType` | One per active AIS segment |
| AIS-4, AIG-8, AIL-6, AIP-6 | `start` | Earliest value; used when SCH-11.4 is empty |
| AIS-7/8, AIG-11/12, AIL-9/10, AIP-9/10 | `end` | Latest start + duration; used when neither SCH-11.5 nor SCH-9 gives an end |
| (computed) | `minutesDuration` | Whole minutes between `start` and `end` |
| NTE-3 | `comment` | Multiple NTE segments joined with newlines |
| PID | `participant` (patient) | `required` = `required`, `status` = `accepted`, `actor.display` from PID-5 |
| AIP-3, AIP-4 | `participant` (practitioner) | `type` from AIP-4: known role codes (e.g. `ATND`) use `v3-ParticipationType`, others a local code system; actor references the AU Core Practitioner |
| AIL-3 | `participant` (location) | Actor references the AU Core Location |
| AIG-3, AIG-4 | `participant` | `actor.display` only; no resource is created; `type` as for AIP-4 |
| MSH-7 | [sourceMessageDateTime](StructureDefinition-source-message-datetime.html) | |
| MSH-10 | [sourceMessageControlId](StructureDefinition-source-message-control-id.html) | |
{:.grid}

**Resource segment action codes.** AIS, AIG, AIL or AIP segments with action code (field 2) `D` are left out of the Appointment. Because each message rebuilds the Appointment, this removes the resource.

**Duration units** recognised (case-insensitive): s, sec, min, minute(s), h, hr, hour(s), d, day(s). Empty units are treated as minutes and a warning is logged.

**Timestamps** that carry a UTC offset keep it. Those without one get the configured default time zone (`DEFAULT_TZ`, default Australia/Brisbane).

#### Status rules

| Trigger | SCH-25 present | SCH-25 empty |
|---|---|---|
| S12 | mapped value | `booked` |
| S13, S14 | mapped value | existing status kept (`booked` if the Appointment is new) |
| S15 | `cancelled` | `cancelled` |
{:.grid}

FHIR R4 invariant app-3 requires `start` and `end` unless the status is `proposed`, `cancelled` or `waitlist`.
A message that would produce any other status without both times is rejected with `AE`.

### PID → AU Core Patient

Profile: [AU Core Patient](https://hl7.org.au/fhir/core/StructureDefinition-au-core-patient.html)

| HL7 v2 | FHIR Patient | Notes |
|---|---|---|
| PID-3, CX.5 = `NI` (CX.4 `AUSHIC`) | `identifier` (AU IHI) | system `http://ns.electronichealth.net.au/id/hi/ihi/1.0`, type v2-0203 `NI`. Must be 16 digits, start 800360 and pass the Luhn check, otherwise it is dropped with a warning |
| PID-3, CX.5 = `MC` | `identifier` (AU Medicare Card Number) | system `http://ns.electronichealth.net.au/id/medicare-number`, type `MC`; 10 or 11 digits, otherwise dropped. CX.8 → `period.end` |
| PID-3, CX.4 = `AUSDVA` | `identifier` (generic) | AU DVA Number needs a DVA entitlement type that SIU doesn't carry, so it's kept as a local identifier with a warning |
| PID-3, CX.5 = `MR` | `identifier` | system `http://example.org/fhir/sid/mrn/{CX.4}` (fixed rule; `MRN_SYSTEM_BASE` configurable), type `MR`. No assigner, so it is a plain identifier in AU Core Patient rather than the AU Medical Record Number profile |
| PID-3, CX.5 = `PI` | `identifier` | `{base}/patient/{CX.4}/PI`, type `PI`, no assigner |
| PID-3, other types | `identifier` | `{base}/patient/{CX.4}/{CX.5}` |
| PID-5 | `name` | As the base mapping, plus `name.text`. If no name has a family name, an extra name holding only a data-absent-reason extension is added (au-core-pat-02 / au-core-pat-03) |
| PID-7 | `birthDate` | Mandatory in AU Core: if empty, `_birthDate` carries data-absent-reason `unknown`. Invalid values → `AE` |
| PID-8 | `gender` | Mandatory in AU Core: if empty → `unknown`. Codes via [HL70001ToAdministrativeGender](ConceptMap-HL70001ToAdministrativeGender.html) |
| PID-10 | `extension:indigenousStatus` | Codes 1, 2, 3, 4, 9 → Australian Indigenous Status. Assumes the sender uses PID-10 for Indigenous status (switch off with `INDIGENOUS_STATUS_FROM_PID10=false`) |
| PID-11 | `address` | Shaped for AU Base Australian Address when Australian: state names → codes (e.g. Queensland → QLD), country AU/AUS/Australia → `AU`, `text` always set. Bad state or postcode → sent as a plain Address with a warning |
| PID-13 / PID-14 | `telecom` | Unchanged from the base mapping |
| PID-15 | `communication.language` | CE.1 as a BCP-47 code when CE.3 is ISO639 / BCP47, otherwise text only |
{:.grid}

At least one usable identifier must remain after these checks (au-core-pat-01), otherwise the message gets `AE`.

### AIP-3 → AU Core Practitioner

Profile: [AU Core Practitioner](https://hl7.org.au/fhir/core/StructureDefinition-au-core-practitioner.html)

| HL7 v2 | FHIR Practitioner | Notes |
|---|---|---|
| AIP-3.1 with XCN.13 = `NPI` (or XCN.9 `AUSHIC`) | `identifier` (AU HPI-I) | system `http://ns.electronichealth.net.au/id/hi/hpii/1.0`, type `NPI`; 16 digits, prefix 800361, Luhn. Invalid → kept as a local identifier |
| AIP-3.1 with XCN.9 = `AUSHICPR` | `identifier` (AU Medicare Provider Number) | system `http://ns.electronichealth.net.au/id/medicare-provider-number`, type `http://terminology.hl7.org.au/CodeSystem/v2-0203#UPIN` |
| AIP-3.1, other | `identifier` | `{base}/practitioner/{XCN.9}` |
| AIP-3.2 | `name.family` | **Required by AU Core.** Without it no Practitioner is created; the appointment gets a display-only participant |
| AIP-3.3, AIP-3.6 | `name.given`, `name.prefix` | `name.text` = prefix given family |
{:.grid}

### AIL-3 → AU Core Location and AU Core Organization

| HL7 v2 | FHIR | Notes |
|---|---|---|
| AIL-3.4/.1/.2/.3 | `Location.identifier` | Facility/point of care/room/bed joined with `/`; system `{base}/location`. Satisfies au-core-loc-01 |
| AIL-3.9 | `Location.name` | Falls back to the identifier parts |
| AIL-4 | `Location.type` | Translated with the registry's `locationTypes` to ServiceDeliveryLocationRoleType - AU Extended; untranslated codes are sent as local codes with a warning |
| AIL-3 bed / room / point of care | `Location.physicalType` | Most specific part present → `bd` / `ro` / `wa` (location-physical-type) |
| AIL-3.4 (facility) | `Location.managingOrganization` → AU Core Organization | Looked up on the FHIR server by `http://example.org/fhir/sid/organization` + facility code and used unchanged. If none exists, a placeholder (name = facility code, tag `placeholder`) is created with a conditional create. The service never modifies an existing Organization |
| (from the Organization) | `Location.address` | The Organization's first address, if it has one |
{:.grid}

`{base}` is the configurable identifier system base (`IDENTIFIER_SYSTEM_BASE`, default `http://example.org/fhir/sid`).

### Coded values

CE/CWE fields become a CodeableConcept with one coding: code = component 1, display = component 2.
A coding system of `HL70276` becomes `http://terminology.hl7.org/CodeSystem/v2-0276`.
Any other coding system name becomes the placeholder `http://example.org/fhir/CodeSystem/v2-local/{name}`.
