# SIU → FHIR AU Core service and implementation guide (proof of concept)

Receives HL7 v2 **SIU S12/S13/S14/S15** messages and writes FHIR R4 resources conforming to
**AU Core 2.0.0** (Patient, Practitioner, Location, Organization) plus an Appointment profile, to a
HAPI FHIR server. Includes a FSH implementation guide that depends on AU Core 2.0.0, and a GitHub
workflow that builds the guide and publishes it to GitHub Pages.

This is a separate code base from the base PoC (`siu-fhir-poc`); the Python package is `siu2fhir_au`.

**Simulated data only. No authentication anywhere.** IHI, HPI-I, HPI-O and Medicare numbers in the
samples are synthetic: they pass the AU Base format checks but weren't issued to anyone.

```
siu2fhir_au/   service: hl7v2.py, mapping.py, au.py (AU Core rules), processor.py, servers.py
config/        au-registry.json - AIL-4 location type translations (the only local config left)
seed/          organizations.json - facility Organizations to load onto the FHIR server (tools/seed_fhir.py)
samples/       01-04 S12→S15 lifecycle, 05 AIS-only timing, 06 missing data
tests/         unittest suite (python -m unittest discover -s tests)
ig/            FSH implementation guide (sushi-config.yaml depends on hl7.fhir.au.core 2.0.0)
scripts/       install_fhir_packages.py, build_ig.py
.github/       ig-publish.yml (tests → IG build → GitHub Pages), dependabot.yml
```

## Run the service

**Python setup.** From the project root: create a virtual environment, then
`pip install -r requirements.txt`. The only package is `tzdata` - the time zone database Python's
`zoneinfo` needs on **Windows**. Without it the tests fail to import with
`ZoneInfoNotFoundError: 'No time zone found with key Australia/Brisbane'`.


```bash
docker compose up --build                       # HAPI on :8080, MLLP :2575, HTTP :8090
python3 tools/send_mllp.py samples/0*.hl7
python3 -m unittest discover -s tests -v        # no HAPI needed
```

Configuration (environment variables) is as for the base PoC, plus:

| Variable | Default | Purpose |
|---|---|---|
| `IG_CANONICAL` | `http://example.org/fhir/siu2fhir-au` | Base for the extension / profile URLs the service writes. **Must equal `canonical` in `ig/sushi-config.yaml`** |
| `AU_REGISTRY` | `config/au-registry.json` | Local registry file |
| `MRN_SYSTEM_BASE` | `http://example.org/fhir/sid/mrn` | MRN identifier system = `<base>/<PID-3.4>`; no assigner is sent |
| `PATIENT_PRACTITIONER_WRITE_MODE` | `create-only` | `create-only`: an existing Patient / Practitioner on the server is used unchanged, and one is created from the SIU only if none matches. `upsert`: the SIU data overwrites it (conditional update - the original behaviour) |
| `ORGANIZATION_ID_SYSTEM` | `http://example.org/fhir/sid/organization` | Identifier system used to find a facility's Organization (value = AIL-3.4) |
| `INDIGENOUS_STATUS_FROM_PID10` | `true` | Map PID-10 to the Indigenous status extension |
| `SET_META_PROFILE` | `true` | Put AU Core / IG profile URLs in `meta.profile` |

## Facilities (Organizations) live on the FHIR server

For each facility code in AIL-3.4 the service searches the FHIR server for
`Organization?identifier=http://example.org/fhir/sid/organization|<facility code>`:

- **Found:** it's referenced from the Location as is and **never modified**, so curated names,
  addresses, telecoms and HPI-Os are kept. The Location's `address` is copied from the Organization's
  first address, and `managingOrganization.display` is its name.
- **Not found:** a placeholder Organization is created (`name` = facility code, tagged
  `meta.tag = <IG canonical>/CodeSystem/siu2fhir-tag|placeholder`, using a conditional create so
  it can't be duplicated) and a warning is logged. Curate it on the server later; the service won't
  overwrite your changes. Find placeholders with `GET /fhir/Organization?_tag=placeholder`.

Load your facilities before sending messages:

```bash
python tools/seed_fhir.py                     # seed/organizations.json -> $FHIR_BASE_URL (default localhost:8080)
python tools/seed_fhir.py --transaction       # or post the file as one FHIR transaction
```

The seed file is an ordinary FHIR transaction Bundle of Organizations, each with the
`http://example.org/fhir/sid/organization` identifier; re-running it updates rather than duplicates.
Sample 05 uses facility `SATELLITE`, which isn't seeded, to show the placeholder.

## Existing Patients and Practitioners are not overwritten

By default (`PATIENT_PRACTITIONER_WRITE_MODE=create-only`) the service searches for the Patient (first
PID-3 identifier) and each Practitioner (AIP-3 identifier). If one exists it is referenced from the
Appointment and **never modified** - the server's copy is assumed to be richer or more accurate - and the
Appointment's participant display is taken from it. Only when none exists is one created from the SIU
data, using `POST` with `If-None-Exist` so it can't be duplicated.

Consequences: demographic changes in later SIU messages are not applied, and a Patient on the server
that doesn't carry the first PID-3 identifier won't be matched (a second Patient is created). Set
`PATIENT_PRACTITIONER_WRITE_MODE=upsert` to go back to overwriting from the SIU data. Locations are
still created or updated from the SIU message either way.

## Build the implementation guide locally

### 1. Install the tools (once)

| Tool | Check | Install |
|---|---|---|
| Java 17+ (recommended) | `java -version` | e.g. Eclipse Temurin |
| Node.js (LTS) | `node -v` | nodejs.org |
| SUSHI | `sushi --version` | `npm install -g fsh-sushi` |
| Ruby + Jekyll | `jekyll -v` | Ruby from ruby-lang.org (Windows: RubyInstaller with DevKit), then `gem install jekyll` |
| Python 3.10+ | `python --version` | for the helper scripts |

Check the current requirements on the [IG Publisher](https://confluence.hl7.org/display/FHIR/IG+Publisher+Documentation)
and [SUSHI](https://fshschool.org/docs/sushi/installation/) pages - I couldn't confirm exact minimum versions.

### 2. Install the AU Core and AU Base packages

`ig/sushi-config.yaml` lists both dependencies:

```yaml
dependencies:
  hl7.fhir.au.core: 2.0.0
  hl7.fhir.au.base: 6.0.0
```

SUSHI and the IG Publisher keep packages in the local FHIR package cache,
`~/.fhir/packages` (Windows: `%USERPROFILE%\.fhir\packages`), one folder per package:
`hl7.fhir.au.core#2.0.0/package/...`. When online they download anything missing automatically,
so step 2 is optional. To install explicitly - or offline - use one of:

**a) The helper script** (downloads from packages.fhir.org and follows each package's dependencies):

```bash
python scripts/install_fhir_packages.py                          # everything sushi-config.yaml needs
python scripts/install_fhir_packages.py hl7.fhir.au.core#2.0.0   # a specific package
python scripts/install_fhir_packages.py --list                   # what's in the cache
```

**b) From downloaded files** (no registry access needed on the build machine). Download the `.tgz`
files from the FHIR package registry on another machine - for example
`https://packages.fhir.org/hl7.fhir.au.core/2.0.0` and `https://packages.fhir.org/hl7.fhir.au.base/6.0.0` - then:

```bash
python scripts/install_fhir_packages.py --no-deps \
  --tgz hl7.fhir.au.core-2.0.0.tgz --tgz hl7.fhir.au.base-6.0.0.tgz
```

AU Base also depends on other packages (for example HL7 Terminology), which are needed too;
drop `--no-deps` if the machine can reach the registry. `hl7.fhir.r4.core#4.0.1` is always needed.

**c) By hand**: extract a `.tgz` so that its `package/` folder sits at
`~/.fhir/packages/<id>#<version>/package/` (for example `~/.fhir/packages/hl7.fhir.au.core#2.0.0/package/package.json`).

### 3. Build

```bash
python scripts/build_ig.py --sushi-only     # quick FSH check: ig/fsh-generated/
python scripts/build_ig.py                  # full build: ig/output/index.html, QA in ig/output/qa.html
python scripts/build_ig.py --update         # also fetch the latest publisher.jar
```

`build_ig.py` downloads `publisher.jar` to `ig/input-cache/` on first use. Equivalent manual commands:

```bash
cd ig
sushi .
java -jar input-cache/publisher.jar -ig .
```

The publisher needs internet access for its template and the terminology server (tx.fhir.org).
`--offline` passes `-tx n/a`, which skips terminology validation.

### 4. Keep the examples in sync

`ig/input/fsh/examples.fsh` is generated by running the samples through the service. After changing
the mapping code, samples or registry:

```bash
python ig/tools/gen_examples.py
```

The GitHub workflow fails if this file is out of date.

## Publish to GitHub Pages

1. Create a GitHub repository and push this project to its `main` branch.
2. In the repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Push (or run the workflow from the **Actions** tab). `.github/workflows/ig-publish.yml` then:
   - runs the unit tests;
   - installs Java, Node + SUSHI, Ruby + Jekyll, and the FHIR packages (cached between runs);
   - checks `examples.fsh` is current;
   - runs the IG Publisher and writes a QA summary to the run page (full report: `qa-report` artifact);
   - on `main`, uploads `ig/output` and deploys it to `https://<owner>.github.io/<repo>/`.
4. Pull requests build and report QA but don't deploy.

Set `FAIL_ON_QA_ERRORS: "true"` in the workflow to block publishing when the QA report has errors.
`dependabot.yml` keeps the action versions current.

**Canonical URL.** The guide's canonical is a placeholder (`http://example.org/fhir/siu2fhir-au`). If you
want it to resolve to the Pages site, set `canonical` in `ig/sushi-config.yaml` to the Pages URL, set
`IG_CANONICAL` for the service to the same value, and re-run `python ig/tools/gen_examples.py`.

## What changed from the base PoC (AU Core)

See `ig/input/pagecontent/au-core.md` (the "AU Core Conformance" page) for details. In short:
AU national identifier systems with format checks (IHI, Medicare, HPI-I, provider number); mandatory
gender, birth date and family name with data-absent-reason fallbacks; Practitioners need a family name;
Australian address normalisation; Indigenous status (PID-10) and language (PID-15); an AU Core
Organization per facility (looked up on the FHIR server, placeholder if missing), referenced from Location; Location physical type; participant role codes
in `v3-ParticipationType`.

## Unverified items

Not confirmed against the published specifications when this was written (also on the IG's Open Issues page):

- Canonical URLs of AU Core Practitioner, PractitionerRole, Location and Organization (AU Core Patient's was confirmed: `http://hl7.org.au/fhir/core/StructureDefinition/au-core-patient`).
- HPI-O identifier system and type coding - so the seed Organization doesn't carry an HPI-O.
- Code values: Australian States and Territories, Indigenous status (1, 2, 3, 4, 9), location-physical-type (`bd`, `ro`, `wa`).
- Australian v2 conventions for identifiers and PID-10 - confirm with your sending system.
- GitHub action major versions other than `upload-pages-artifact@v5`; Dependabot will correct them.
- **Neither SUSHI nor the IG Publisher has been run on this guide** (the registry wasn't reachable where it was written). Expect fixes on the first build.
