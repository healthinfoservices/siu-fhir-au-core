"""Send HL7 v2 message files over MLLP and print each ACK.

Usage: python tools/send_mllp.py [--host localhost] [--port 2575] FILE [FILE ...]
Files may use CR, LF or CRLF segment terminators; they are sent with CR.
"""
from __future__ import annotations

import argparse
import re
import socket
import sys

SB, EB, CR = b"\x0b", b"\x1c", b"\x0d"


def send(host: str, port: int, text: str, timeout: float = 30.0) -> str:
    text = "\r".join(s for s in re.split(r"\r\n|\r|\n", text) if s.strip())
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(SB + text.encode("utf-8") + EB + CR)
        buf = b""
        while EB + CR not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    start = buf.find(SB)
    end = buf.find(EB + CR)
    return buf[start + 1:end].decode("utf-8", "replace") if start >= 0 and end > start else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=2575)
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    rc = 0
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            ack = send(args.host, args.port, f.read())
        msa = next((s for s in ack.split("\r") if s.startswith("MSA")), "MSA|??")
        print(f"{path}: {msa}")
        for s in ack.split("\r"):
            if s.startswith("ERR"):
                print("   ", s)
        if not msa.startswith("MSA|AA"):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
