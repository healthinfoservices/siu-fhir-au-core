The service reads a small JSON registry (`config/au-registry.json`, or the path in the `AU_REGISTRY` environment variable) for the one thing SIU doesn't carry and the FHIR server doesn't hold: translations of local location type codes.

| Registry section | Keyed by | Used for |
|---|---|---|
| `locationTypes.{code}` | AIL-4.1 | A Coding from ServiceDeliveryLocationRoleType - AU Extended for `Location.type`. Untranslated codes are sent as local codes with a warning |
{:.grid}

Keys starting with `_` are ignored, so they can hold comments and examples.

Everything else that used to need local configuration is handled without it:

| Need | How it's met |
|---|---|
| Facility name, address, HPI-O | Organizations on the FHIR server, found by `http://example.org/fhir/sid/organization` + AIL-3.4 and never modified; a tagged placeholder is created when missing. Load them with `tools/seed_fhir.py` |
| MRN namespace | Fixed rule: `http://example.org/fhir/sid/mrn/` + PID-3.4. No assigner is sent |
{:.grid}

The location type translations could later move onto the FHIR server as a ConceptMap.
