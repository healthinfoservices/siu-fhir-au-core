### Assumptions to confirm with the sending system

| # | Item | Notes |
|---|---|---|
| 1 | IHI sent as `^^^AUSHIC^NI`, Medicare as `^^^AUSHIC^MC`, HPI-I with XCN.13 `NPI`, Medicare provider number with XCN.9 `AUSHICPR` | Taken from a secondary source citing AS 4700.1, not from the standard itself |
| 2 | Indigenous status in PID-10 using codes 1, 2, 3, 4, 9 | Can be switched off with `INDIGENOUS_STATUS_FROM_PID10=false` |
| 3 | DVA numbers | AU DVA Number requires a DVA entitlement type, which SIU doesn't carry; DVA numbers are kept as local identifiers |
| 4 | Language in PID-15 coded as ISO 639 | Other coding systems are sent as text only |
{:.grid}

### Not yet verified against the published specifications

| # | Item |
|---|---|
| 1 | Canonical URLs of AU Core Practitioner, PractitionerRole, Location and Organization (the AU Core Patient canonical was confirmed; the others follow the same pattern) |
| 2 | HPI-O identifier system and type coding (so the seed Organization doesn't carry an HPI-O) |
| 3 | Code values: Australian States and Territories, Australian Indigenous Status, location-physical-type (`bd`, `ro`, `wa`), and any location type codes you add to the registry |
| 4 | That `urn:ietf:bcp:47` codes satisfy the Common Languages in Australia binding |
{:.grid}

### Carried over from the base proof of concept

* Each SIU message rebuilds the whole Appointment, so edits made directly in FHIR are overwritten by the next message for that appointment.
* Differences from the HL7 v2-to-FHIR IG: SCH-7 → `appointmentType`, Started → `arrived`, resource timing rolled up to `Appointment.start`/`end`.
* No `Slot` or `Schedule` resources; no authentication or TLS.
