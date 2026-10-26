#!/usr/bin/env python3
"""Install FHIR NPM packages (and their dependencies) into the local FHIR package cache.

SUSHI and the IG Publisher read packages from the cache (default ~/.fhir/packages), where
each package lives in "<id>#<version>/package/". They download missing packages themselves
when they're online; this script lets you pre-install them, pin them, or install from
.tgz files you downloaded yourself (for example behind a firewall).

Usage
  python scripts/install_fhir_packages.py                         # what ig/sushi-config.yaml depends on
  python scripts/install_fhir_packages.py hl7.fhir.au.core#2.0.0  # specific packages
  python scripts/install_fhir_packages.py --tgz au-core-2.0.0.tgz --tgz au-base-6.0.0.tgz
  python scripts/install_fhir_packages.py --no-deps hl7.fhir.au.base#6.0.0
  python scripts/install_fhir_packages.py --list

Options
  --cache DIR     package cache folder (default: $FHIR_PACKAGE_CACHE or ~/.fhir/packages)
  --registry URL  package registry (default: https://packages.fhir.org; packages2.fhir.org is tried next)
  --force         re-install packages already in the cache
Standard library only; works on Windows, macOS and Linux.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRIES = ["https://packages.fhir.org", "https://packages2.fhir.org/packages"]


def cache_dir(arg: str | None) -> pathlib.Path:
    return pathlib.Path(arg or os.getenv("FHIR_PACKAGE_CACHE") or pathlib.Path.home() / ".fhir" / "packages")


def sushi_dependencies() -> dict[str, str]:
    """Read `dependencies:` from ig/sushi-config.yaml (simple parser, no YAML library needed)."""
    deps, inside = {}, False
    for line in (ROOT / "ig" / "sushi-config.yaml").read_text(encoding="utf-8").splitlines():
        if re.match(r"^dependencies:\s*$", line):
            inside = True
            continue
        if inside:
            if line and not line.startswith((" ", "\t")):
                break
            m = re.match(r"^\s+([A-Za-z0-9._-]+):\s*['\"]?([^'\"\s#]+)", line)
            if m:
                deps[m.group(1)] = m.group(2)
    return deps


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/tar+gzip, application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def resolve_version(pkg: str, spec: str, registries: list[str]) -> str | None:
    """Exact versions pass through; '6.x', 'latest' etc. are resolved from registry metadata."""
    if re.fullmatch(r"\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?", spec):
        return spec
    if spec == "current" or spec.startswith("dev"):
        return None                      # CI builds aren't in the registry; the IG Publisher fetches them
    for reg in registries:
        try:
            meta = json.loads(fetch(f"{reg}/{pkg}"))
        except (urllib.error.URLError, ValueError):
            continue
        versions = list(meta.get("versions", {}))
        if spec == "latest":
            return meta.get("dist-tags", {}).get("latest") or (versions[-1] if versions else None)
        prefix = spec.rstrip("x*").rstrip(".")
        matches = [v for v in versions if v == prefix or v.startswith(prefix + ".")]
        if matches:
            return sorted(matches, key=lambda v: [int(x) if x.isdigit() else -1 for x in re.split(r"[.-]", v)])[-1]
    return None


def extract(data: bytes, dest: pathlib.Path) -> dict:
    """Extract a package .tgz into dest (expects a top-level 'package/' folder). Returns package.json."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fhirpkg-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                target = (tmp / member.name).resolve()
                if not str(target).startswith(str(tmp.resolve())):
                    raise RuntimeError(f"unsafe path in archive: {member.name}")
            if hasattr(tarfile, "data_filter"):        # Python 3.12+ (and security backports)
                tf.extractall(tmp, filter="data")
            else:
                tf.extractall(tmp)
        src = tmp / "package"
        if not src.is_dir():
            raise RuntimeError("archive has no 'package/' folder - is it a FHIR NPM package?")
        manifest = json.loads((src / "package.json").read_text(encoding="utf-8"))
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        shutil.move(str(src), str(dest / "package"))
        return manifest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install(pkg: str, spec: str, cache: pathlib.Path, registries: list[str], force: bool,
            deps: bool, seen: set[str]) -> None:
    version = resolve_version(pkg, spec, registries)
    if version is None:
        print(f"  skip   {pkg}#{spec} (not resolvable from the registry; the IG Publisher will fetch it)")
        return
    key = f"{pkg}#{version}"
    if key in seen:
        return
    seen.add(key)
    dest = cache / key
    manifest_path = dest / "package" / "package.json"
    if manifest_path.exists() and not force:
        print(f"  cached {key}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        data, last_err = None, None
        for reg in registries:
            try:
                data = fetch(f"{reg}/{pkg}/{version}")
                break
            except urllib.error.URLError as e:
                last_err = e
        if data is None:
            raise SystemExit(f"Could not download {key}: {last_err}. Download the .tgz by hand and use --tgz.")
        manifest = extract(data, dest)
        print(f"  added  {key}")
    if deps:
        for dep, dep_spec in (manifest.get("dependencies") or {}).items():
            install(dep, dep_spec, cache, registries, force, deps, seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packages", nargs="*", help="id#version, e.g. hl7.fhir.au.core#2.0.0")
    ap.add_argument("--tgz", action="append", default=[], help="install from a downloaded .tgz file")
    ap.add_argument("--cache")
    ap.add_argument("--registry")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-deps", action="store_true")
    ap.add_argument("--list", action="store_true", help="list packages in the cache")
    args = ap.parse_args()

    cache = cache_dir(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    if args.list:
        for p in sorted(cache.iterdir()):
            if (p / "package" / "package.json").exists():
                print(p.name)
        return 0
    registries = [args.registry.rstrip("/")] if args.registry else REGISTRIES
    print(f"FHIR package cache: {cache}")
    seen: set[str] = set()

    for path in args.tgz:
        data = pathlib.Path(path).read_bytes()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            m = json.load(tf.extractfile("package/package.json"))
        key = f"{m['name']}#{m['version']}"
        extract(data, cache / key)
        seen.add(key)
        print(f"  added  {key} (from {path})")
        if not args.no_deps:
            for dep, spec in (m.get("dependencies") or {}).items():
                install(dep, spec, cache, registries, args.force, True, seen)

    wanted = {}
    for p in args.packages:
        pkg, _, ver = p.partition("#")
        wanted[pkg] = ver or "latest"
    if not args.packages and not args.tgz:
        wanted = sushi_dependencies()
        wanted.setdefault("hl7.fhir.r4.core", "4.0.1")
        print("Installing ig/sushi-config.yaml dependencies: " + ", ".join(f"{k}#{v}" for k, v in wanted.items()))
    for pkg, spec in wanted.items():
        install(pkg, spec, cache, registries, args.force, not args.no_deps, seen)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
