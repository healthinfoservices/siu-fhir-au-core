Extension: SourceMessageDateTime
Id: source-message-datetime
Title: "Source Message Date/Time"
Description: """
The MSH-7 (date/time of message) of the most recent HL7 v2 SIU message applied to this
Appointment. The ingestion service compares an incoming message's MSH-7 with this value
and ignores messages that are older, so a delayed message cannot undo a later change.
"""
Context: Appointment
* value[x] 1..1
* value[x] only dateTime

Extension: SourceMessageControlId
Id: source-message-control-id
Title: "Source Message Control ID"
Description: """
The MSH-10 (message control ID) of the most recent HL7 v2 SIU message applied to this
Appointment. Provides traceability back to the interface engine's message log.
"""
Context: Appointment
* value[x] 1..1
* value[x] only string
