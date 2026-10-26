#!/usr/bin/env python3
"""Build the implementation guide locally: SUSHI, then the HL7 IG Publisher.

  python scripts/build_ig.py                 # build (downloads publisher.jar on first run)
  python scripts/build_ig.py --update        # fetch the latest publisher.jar first
  python scripts/build_ig.py --sushi-only    # just compile FSH (fast check)
  python scripts/build_ig.py --offline       # no terminology server (-tx n/a); packages must be cached

Output: ig/output/index.html  (QA report: ig/output/qa.html)
Needs: Java (17+ recommended), Node.js + SUSHI (npm install -g fsh-sushi), Ruby + Jekyll.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
IG = ROOT / "ig"
JAR = IG / "input-cache" / "publisher.jar"
JAR_URL = "https://github.com/HL7/fhir-ig-publisher/releases/latest/download/publisher.jar"


def need(cmd: str, hint: str) -> str:
    path = shutil.which(cmd)
    if not path:
        sys.exit(f"'{cmd}' not found on PATH. {hint}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="download the latest publisher.jar")
    ap.add_argument("--sushi-only", action="store_true")
    ap.add_argument("--offline", action="store_true", help="pass -tx n/a (no terminology server)")
    args = ap.parse_args()

    sushi = need("sushi", "Install Node.js, then: npm install -g fsh-sushi")
    print("== SUSHI")
    subprocess.run([sushi, "."], cwd=IG, check=True)
    if args.sushi_only:
        return 0

    java = need("java", "Install a Java runtime (17 or later recommended).")
    need("jekyll", "Install Ruby, then: gem install jekyll")
    if args.update or not JAR.exists():
        print(f"== Downloading {JAR_URL}")
        JAR.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(JAR_URL, JAR)

    print("== IG Publisher")
    cmd = [java, "-Xmx4g", "-jar", str(JAR), "-ig", "."]
    if args.offline:
        cmd += ["-tx", "n/a"]
    subprocess.run(cmd, cwd=IG, check=True)

    qa = IG / "output" / "qa.json"
    if qa.exists():
        q = json.loads(qa.read_text(encoding="utf-8"))
        print(f"== QA: {q.get('errs', '?')} errors, {q.get('warnings', '?')} warnings, {q.get('hints', '?')} hints "
              f"- see ig/output/qa.html")
    print(f"== Done: {IG / 'output' / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
