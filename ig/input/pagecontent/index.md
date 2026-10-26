### Purpose

This implementation guide documents a **proof of concept** that turns an HL7 v2 scheduling feed into FHIR R4 resources conforming to **AU Core 2.0.0**.
A Python ingestion service receives SIU S12, S13, S14 and S15 messages, converts them, and writes them to a HAPI FHIR server.
A web front end (planned: Vue/Vuetify) reads appointments directly from that server.

<div class="dragon">
This guide describes a proof of concept that uses <b>simulated data only</b>. It is not intended for clinical use, and has not been balloted or reviewed.
IHI, HPI-I and Medicare numbers in the examples are <b>synthetic</b>: they pass the AU Base format checks but were not issued to anyone.
The canonical URL, local identifier systems and local code systems are <code>example.org</code> placeholders.
</div>

### What conforms to what

| Resource | Profile | Populated from |
|---|---|---|
| Patient | [AU Core Patient](https://hl7.org.au/fhir/core/StructureDefinition-au-core-patient.html) | PID |
| Practitioner | [AU Core Practitioner](https://hl7.org.au/fhir/core/StructureDefinition-au-core-practitioner.html) | AIP-3 |
| Location | [AU Core Location](https://hl7.org.au/fhir/core/StructureDefinition-au-core-location.html) | AIL-3, AIL-4 |
| Organization | [AU Core Organization](https://hl7.org.au/fhir/core/StructureDefinition-au-core-organization.html) | AIL-3.4 facility, looked up on the FHIR server |
| Appointment | [SIU AU Appointment](StructureDefinition-siu-au-appointment.html) (this guide) | SCH, AIS, AIG, AIL, AIP, NTE |
{:.grid}

AU Core 2.0.0 has no Appointment profile, so this guide defines one whose participants reference the AU Core resources.

### Scope

| Event | Meaning | Effect |
|---|---|---|
| S12 | New appointment booking | Create the Appointment (or update it if the ID already exists) |
| S13 | Reschedule | Rebuild the Appointment with the new times |
| S14 | Modification | Rebuild the Appointment with the changed details |
| S15 | Cancellation | Set status to `cancelled` and record the reason |
{:.grid}

### Dependencies

{% include dependency-table.xhtml %}

### How to read this guide

* [AU Core Conformance](au-core.html): what changes compared with a plain FHIR R4 mapping, and why.
* [Mapping](mapping.html): field-level HL7 v2 to FHIR rules.
* [Local Registry](registry.html): local configuration (location type translations), and how facilities and MRN namespaces are handled without it.
* [Processing](messaging.html): matching, ordering and acknowledgements.
* [Worked Example](lifecycle.html): one appointment through S12 → S13 → S14 → S15, plus a missing-data example.
* [Building This Guide](building.html): local build and the GitHub Pages workflow.
* [Open Issues](open-issues.html).
