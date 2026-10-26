// Patient, Practitioner, Location and Organization are AU Core 2.0.0 profiles used as-is.
// Appointment has no AU Core (or AU Base) profile, so this IG defines one.

Profile: SIUAUAppointment
Parent: Appointment
Id: siu-au-appointment
Title: "SIU AU Appointment"
Description: """
An Appointment created and maintained from HL7 v2 SIU S12, S13, S14 and S15 messages,
whose participants are AU Core resources. The ingestion service rebuilds the whole
resource from each message it applies.
"""
* obeys siu-appt-1 and siu-appt-2
* extension contains
    SourceMessageDateTime named sourceMessageDateTime 0..1 MS and
    SourceMessageControlId named sourceMessageControlId 0..1 MS
* identifier 1..* MS
* identifier ^short = "SCH-2 filler and/or SCH-1 placer appointment ID"
* identifier.type 1..1 MS
* identifier.type from AppointmentIdentifierType (required)
* identifier.system 1..1 MS
* identifier.value 1..1 MS
* status MS
* status ^short = "From SCH-25 (table 0278) or the trigger event; S15 always gives cancelled"
* cancelationReason MS
* cancelationReason ^short = "SCH-6 event reason, populated only when status is cancelled"
* serviceType MS
* serviceType ^short = "AIS-3 universal service identifier"
* appointmentType MS
* appointmentType ^short = "SCH-7 appointment reason (HL7 table 0276)"
* start MS
* start ^short = "SCH-11.4, else the earliest AIS-4 / AIG-8 / AIL-6 / AIP-6"
* end MS
* end ^short = "SCH-11.5, else start + SCH-9/10, else the latest resource-segment end"
* minutesDuration MS
* comment MS
* comment ^short = "NTE-3 comments, newline-separated"
* participant MS
* participant.type MS
* participant.actor MS
* participant.actor only Reference($AUCorePatient or $AUCorePractitioner or $AUCorePractitionerRole or $AUCoreLocation)
* participant.actor ^short = "AU Core Patient (PID), Practitioner (AIP-3), Location (AIL-3); display-only for AIG and unidentified resources"
* participant.status MS

Invariant: siu-appt-1
Description: "Exactly one participant references the Patient"
Expression: "participant.where(actor.reference.contains('Patient/')).count() = 1"
Severity: #error

Invariant: siu-appt-2
Description: "cancelationReason is only populated for cancelled appointments"
Expression: "cancelationReason.exists() implies status = 'cancelled'"
Severity: #error
