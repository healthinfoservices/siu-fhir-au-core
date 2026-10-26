### Tools

| Tool | Used for | Install |
|---|---|---|
| Java (17 or later recommended) | IG Publisher | e.g. Eclipse Temurin |
| Node.js + SUSHI | Compiling FSH | `npm install -g fsh-sushi` |
| Ruby + Jekyll | Rendering pages (used by the IG Publisher) | `gem install jekyll` |
| Python 3.10+ | Helper scripts, example generation | |
{:.grid}

### Dependencies

This guide depends on **hl7.fhir.au.core 2.0.0**, which depends on **hl7.fhir.au.base 6.0.0** (both listed in `sushi-config.yaml`). SUSHI and the IG Publisher read packages from the local FHIR package cache (`~/.fhir/packages`, one folder per `id#version`) and download missing ones from the FHIR package registry when online.

To pre-install them (and everything they depend on):

```
python scripts/install_fhir_packages.py
```

Behind a firewall, download the `.tgz` files from the registry by another route and install them from disk:

```
python scripts/install_fhir_packages.py --tgz hl7.fhir.au.core-2.0.0.tgz --tgz hl7.fhir.au.base-6.0.0.tgz
```

### Build

```
python scripts/build_ig.py            # SUSHI + IG Publisher; output in ig/output/
python scripts/build_ig.py --sushi-only
```

### Continuous build and GitHub Pages

`.github/workflows/ig-publish.yml` runs the service tests, checks the generated examples are current, builds the guide, and publishes `ig/output` to GitHub Pages from the `main` branch. The QA report is attached to every run as the `qa-report` artifact.
