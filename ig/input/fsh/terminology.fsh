ValueSet: AppointmentIdentifierType
Id: appointment-identifier-type
Title: "Appointment Identifier Type"
Description: "Identifier types used on SIU Appointments: filler (SCH-2) and placer (SCH-1) appointment IDs."
* ^experimental = true
* $v2-0203#FILL
* $v2-0203#PLAC

// ---------------------------------------------------------------------------
// HL7 table 0278 (filler status codes, SCH-25) -> FHIR R4 AppointmentStatus
// ---------------------------------------------------------------------------
Instance: HL70278ToAppointmentStatus
InstanceOf: ConceptMap
Usage: #definition
Title: "HL7 v2 Filler Status (0278) to FHIR AppointmentStatus"
Description: "The mapping the ingestion service applies to SCH-25. Blocked, Overbook and Started have no exact FHIR equivalent."
* name = "HL70278ToAppointmentStatus"
* status = #draft
* experimental = true
* group[0].source = "http://terminology.hl7.org/CodeSystem/v2-0278"
* group[0].target = "http://hl7.org/fhir/appointmentstatus"
* group[0].element[0].code = #Pending
* group[0].element[0].target[0].code = #pending
* group[0].element[0].target[0].equivalence = #equivalent
* group[0].element[1].code = #Waitlist
* group[0].element[1].target[0].code = #waitlist
* group[0].element[1].target[0].equivalence = #equivalent
* group[0].element[2].code = #Booked
* group[0].element[2].target[0].code = #booked
* group[0].element[2].target[0].equivalence = #equivalent
* group[0].element[3].code = #Started
* group[0].element[3].target[0].code = #arrived
* group[0].element[3].target[0].equivalence = #inexact
* group[0].element[3].target[0].comment = "Judgement call: the patient has arrived and the appointment has started."
* group[0].element[4].code = #Complete
* group[0].element[4].target[0].code = #fulfilled
* group[0].element[4].target[0].equivalence = #equivalent
* group[0].element[5].code = #Cancelled
* group[0].element[5].target[0].code = #cancelled
* group[0].element[5].target[0].equivalence = #equivalent
* group[0].element[6].code = #Discontinued
* group[0].element[6].target[0].code = #cancelled
* group[0].element[6].target[0].equivalence = #wider
* group[0].element[6].target[0].comment = "v2.3+ code. Discontinued is treated as cancelled; the HL7 v2-to-FHIR IG leaves it unmapped."
* group[0].element[7].code = #DC
* group[0].element[7].target[0].code = #cancelled
* group[0].element[7].target[0].equivalence = #wider
* group[0].element[7].target[0].comment = "v2.9+ code for Discontinued; treated as cancelled."
* group[0].element[8].code = #Deleted
* group[0].element[8].target[0].code = #entered-in-error
* group[0].element[8].target[0].equivalence = #inexact
* group[0].element[9].code = #Blocked
* group[0].element[9].target[0].code = #booked
* group[0].element[9].target[0].equivalence = #inexact
* group[0].element[9].target[0].comment = "No FHIR equivalent; the time is held so it is treated as booked."
* group[0].element[10].code = #Overbook
* group[0].element[10].target[0].code = #booked
* group[0].element[10].target[0].equivalence = #wider
* group[0].element[11].code = #Noshow
* group[0].element[11].target[0].code = #noshow
* group[0].element[11].target[0].equivalence = #equivalent

// ---------------------------------------------------------------------------
// HL7 table 0001 (administrative sex, PID-8) -> FHIR R4 AdministrativeGender
// ---------------------------------------------------------------------------
Instance: HL70001ToAdministrativeGender
InstanceOf: ConceptMap
Usage: #definition
Title: "HL7 v2 Administrative Sex (0001) to FHIR AdministrativeGender"
Description: "The mapping the ingestion service applies to PID-8. The A and N mappings are judgement calls."
* name = "HL70001ToAdministrativeGender"
* status = #draft
* experimental = true
* group[0].source = "http://terminology.hl7.org/CodeSystem/v2-0001"
* group[0].target = "http://hl7.org/fhir/administrative-gender"
* group[0].element[0].code = #M
* group[0].element[0].target[0].code = #male
* group[0].element[0].target[0].equivalence = #equivalent
* group[0].element[1].code = #F
* group[0].element[1].target[0].code = #female
* group[0].element[1].target[0].equivalence = #equivalent
* group[0].element[2].code = #O
* group[0].element[2].target[0].code = #other
* group[0].element[2].target[0].equivalence = #equivalent
* group[0].element[3].code = #U
* group[0].element[3].target[0].code = #unknown
* group[0].element[3].target[0].equivalence = #equivalent
* group[0].element[4].code = #A
* group[0].element[4].target[0].code = #other
* group[0].element[4].target[0].equivalence = #inexact
* group[0].element[4].target[0].comment = "Ambiguous mapped to other."
* group[0].element[5].code = #N
* group[0].element[5].target[0].code = #unknown
* group[0].element[5].target[0].equivalence = #inexact
* group[0].element[5].target[0].comment = "Not applicable mapped to unknown."

CodeSystem: SIU2FHIRTag
Id: siu2fhir-tag
Title: "SIU2FHIR Resource Tags"
Description: "Tags (meta.tag) the ingestion service puts on resources it creates."
* ^caseSensitive = true
* ^experimental = true
* ^status = #draft
* #placeholder "Placeholder" "Created from an SIU message because no matching resource existed on the FHIR server. Expected to be curated (name, address, identifiers) by an administrator; the service never overwrites it."
