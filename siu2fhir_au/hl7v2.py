"""Minimal, dependency-free HL7 v2 (ER7 / pipe-delimited) parser.

Supports what the SIU mapper needs: segments, fields, repetitions, components,
sub-components, escape sequences (\\F\\ \\S\\ \\T\\ \\R\\ \\E\\) and DTM parsing.

Field numbering follows the HL7 convention: for MSH, MSH-1 is the field
separator itself and MSH-2 the encoding characters, so `msh.field(9)` is the
message type, exactly as in the spec.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional


class HL7ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Delimiters:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"


def unescape(value: str, d: Delimiters) -> str:
    """Decode the standard HL7 escape sequences. Unknown sequences are kept as-is."""
    if d.escape not in value:
        return value
    e = re.escape(d.escape)
    mapping = {"F": d.field, "S": d.component, "T": d.subcomponent,
               "R": d.repetition, "E": d.escape}

    def repl(m: re.Match) -> str:
        code = m.group(1)
        if code in mapping:
            return mapping[code]
        if code.startswith("X") and len(code) > 1:  # hex data
            try:
                return bytes.fromhex(code[1:]).decode("latin-1")
            except ValueError:
                return m.group(0)
        if code in (".br",):
            return "\n"
        return m.group(0)

    return re.sub(f"{e}([^{e}]*){e}", repl, value)


@dataclass
class Segment:
    name: str
    raw_fields: list[str]          # index 0 = segment name
    delims: Delimiters

    # --- raw access -----------------------------------------------------
    def _raw(self, n: int) -> str:
        """Raw (still escaped) text of field n using HL7 numbering."""
        if self.name == "MSH":
            if n == 1:
                return self.delims.field
            if n == 2:
                return self.raw_fields[1] if len(self.raw_fields) > 1 else ""
            idx = n - 1
        else:
            idx = n
        return self.raw_fields[idx] if 0 < idx < len(self.raw_fields) else ""

    # --- convenient accessors ---------------------------------------------
    def repetitions(self, n: int) -> list[str]:
        raw = self._raw(n)
        if self.name == "MSH" and n in (1, 2):
            return [raw]
        return raw.split(self.delims.repetition) if raw else []

    def field(self, n: int, rep: int = 0) -> str:
        """Whole field (first repetition by default), unescaped component text kept raw."""
        reps = self.repetitions(n)
        return reps[rep] if rep < len(reps) else ""

    def component(self, n: int, c: int = 1, rep: int = 0, s: Optional[int] = None) -> str:
        """Unescaped value of field n, component c (1-based), optional sub-component s."""
        f = self.field(n, rep)
        if self.name == "MSH" and n in (1, 2):
            return f
        comps = f.split(self.delims.component)
        val = comps[c - 1] if 0 < c <= len(comps) else ""
        if s is not None:
            subs = val.split(self.delims.subcomponent)
            val = subs[s - 1] if 0 < s <= len(subs) else ""
        return unescape(val, self.delims)

    def components(self, n: int, rep: int = 0) -> list[str]:
        f = self.field(n, rep)
        return [unescape(x, self.delims) for x in f.split(self.delims.component)] if f else []

    def value(self, n: int) -> str:
        """First component of field n, unescaped (the common 'just give me the value' case)."""
        return self.component(n, 1)


@dataclass
class Message:
    segments: list[Segment] = field(default_factory=list)
    delims: Delimiters = field(default_factory=Delimiters)
    raw: str = ""

    def first(self, name: str) -> Optional[Segment]:
        return next((s for s in self.segments if s.name == name), None)

    def all(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]

    @property
    def msh(self) -> Segment:
        seg = self.first("MSH")
        assert seg is not None
        return seg

    @property
    def message_type(self) -> str:
        return self.msh.component(9, 1)

    @property
    def trigger_event(self) -> str:
        return self.msh.component(9, 2)

    @property
    def control_id(self) -> str:
        return self.msh.value(10)


def parse(text: str) -> Message:
    # Strip MLLP framing if a caller passed it through, and normalise terminators.
    text = text.strip("\x0b\x1c\r\n ")
    if not text.startswith("MSH"):
        raise HL7ParseError("Message must start with an MSH segment")
    if len(text) < 8:
        raise HL7ParseError("MSH segment too short")
    fs = text[3]
    enc = text[4:8]
    delims = Delimiters(field=fs, component=enc[0], repetition=enc[1],
                        escape=enc[2], subcomponent=enc[3])
    lines = [ln for ln in re.split(r"\r\n|\r|\n", text) if ln.strip()]
    segs: list[Segment] = []
    for ln in lines:
        parts = ln.split(fs)
        name = parts[0]
        if not re.fullmatch(r"[A-Z0-9]{3}", name):
            raise HL7ParseError(f"Invalid segment name {name!r}")
        segs.append(Segment(name=name, raw_fields=parts, delims=delims))
    return Message(segments=segs, delims=delims, raw=text)


# ---------------------------------------------------------------------------
# Date/time (DTM / TS) handling
# ---------------------------------------------------------------------------
_DTM_RE = re.compile(
    r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(?:\.(\d{1,4}))?([+-]\d{4})?$"
)


def parse_dtm(value: str, default_tz: tzinfo) -> Optional[datetime]:
    """Parse an HL7 DTM ('YYYY[MM[DD[HH[MM[SS[.S[S[S[S]]]]]]]]][+/-ZZZZ]').

    Missing time parts default to zero. A missing offset uses default_tz.
    Returns None for empty input; raises HL7ParseError for malformed input.
    """
    value = (value or "").strip()
    if not value:
        return None
    m = _DTM_RE.match(value)
    if not m:
        raise HL7ParseError(f"Invalid HL7 date/time {value!r}")
    y, mo, d, h, mi, s, frac, off = m.groups()
    micro = int((frac or "0").ljust(6, "0")[:6])
    try:
        naive = datetime(int(y), int(mo or 1), int(d or 1), int(h or 0),
                         int(mi or 0), int(s or 0), micro)
        if off:
            sign = 1 if off[0] == "+" else -1
            tz = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))
            return naive.replace(tzinfo=tz)
    except ValueError:
        # Pattern matched but a part is out of range, e.g. month 13 or offset +2500.
        raise HL7ParseError(f"Invalid HL7 date/time {value!r}") from None
    return naive.replace(tzinfo=default_tz)


def parse_date(value: str) -> Optional[str]:
    """HL7 DT/DTM → FHIR date (YYYY, YYYY-MM or YYYY-MM-DD), keeping the precision supplied.

    The whole value must be a valid DT/DTM (any time part is validated, then dropped);
    anything else raises HL7ParseError.
    """
    value = (value or "").strip()
    if not value:
        return None
    m = _DTM_RE.match(value)
    if not m:
        raise HL7ParseError(f"Invalid HL7 date {value!r}")
    parse_dtm(value, timezone.utc)            # range-checks every part present
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if d:
        return f"{y}-{mo}-{d}"
    if mo:
        return f"{y}-{mo}"
    return y


def format_dtm(dt: datetime) -> str:
    """datetime → HL7 DTM with offset, e.g. 20261007102400+1000."""
    off = dt.strftime("%z") or "+0000"
    return dt.strftime("%Y%m%d%H%M%S") + off
