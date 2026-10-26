### Transport

| Channel | Use | Response |
|---|---|---|
| MLLP, TCP port 2575 | Production-style feed from an interface engine | HL7 ACK, framed with MLLP |
| HTTP `POST /hl7`, port 8090 | Testing | JSON with the ACK, resulting resource references and any warnings |
{:.grid}

MLLP framing is `0x0B` + message + `0x1C 0x0D`. Several messages can be sent on one connection; each gets its own ACK.

### Matching and idempotency

All writes use FHIR conditional update (`PUT [type]?identifier=system|value`), which creates the resource if nothing matches and updates it if one resource matches.
So replaying a message produces the same result and no duplicates.

| Resource | Match key |
|---|---|
| Appointment | SCH-2 filler ID, else SCH-1 placer ID |
| Patient | First PID-3 repetition |
| Practitioner | AIP-3.1 + AIP-3.9 |
| Location | AIL-3 components |
{:.grid}

### Message ordering

The service records the MSH-7 of the last applied message on the Appointment.
A message whose MSH-7 is **earlier** than that value is acknowledged with `AA` but not applied, and a warning is logged.
This stops a delayed S12 from re-booking an appointment that a later S15 cancelled.
Messages with the same MSH-7 are applied, so replays still work.

Ordering depends entirely on the sender's MSH-7 clock. Messages without a parseable MSH-7 skip the check.

### Acknowledgements

Original-mode acknowledgement. In the ACK:

* MSH-3/4 are the service's own configured names (`RECEIVING_APP`, `RECEIVING_FACILITY`).
* MSH-5/6 are the sender's MSH-3/4.
* MSH-9.2, MSH-11 and MSH-12 are echoed from the received message (`P` and `2.5` if empty).
* MSA-2 carries the received MSH-10.

| Situation | MSA-1 | ERR-3 (table 0357) | ERR-4 |
|---|---|---|---|
| Applied, or stale and ignored | `AA` | none | |
| Unparseable message | `AR` | 207 Application internal error | E |
| Message type is not SIU | `AR` | 200 Unsupported message type | E |
| SIU event other than S12–S15 | `AR` | 201 Unsupported event code | E |
| Required data missing (e.g. no timing for a booked appointment) | `AE` | 101 Required field missing | E |
| Invalid value (e.g. bad PID-7 birth date, impossible timestamp, non-numeric or negative duration) | `AE` | 102 Data type error | E |
| FHIR server error or unreachable, or any unexpected error | `AE` | 207 Application internal error | E |
{:.grid}

ERR-8 carries a readable explanation.

Example ACK for a successful S12:

```
MSH|^~\&|SIU2FHIR|POC|PAS|SIMHOSP|20261007100000+1000||ACK^S12^ACK|<generated id>|P|2.5
MSA|AA|MSG0001
```
