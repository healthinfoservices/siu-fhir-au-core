"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Config:
    fhir_base_url: str = os.getenv("FHIR_BASE_URL", "https://gw.interop.community/efiqcon2b/open")
    # Base for identifier systems. Real deployments should use agreed URIs/OIDs
    # (e.g. the AU IHI / Medicare systems); these are placeholders for the PoC.
    identifier_system_base: str = os.getenv(
        "IDENTIFIER_SYSTEM_BASE", "http://example.org/fhir/sid")
    # Used only when an HL7 timestamp carries no UTC offset.
    default_tz_name: str = os.getenv("DEFAULT_TZ", "Australia/Brisbane")
    mllp_host: str = os.getenv("MLLP_HOST", "0.0.0.0")
    mllp_port: int = int(os.getenv("MLLP_PORT", "2575"))
    http_host: str = os.getenv("HTTP_HOST", "0.0.0.0")
    http_port: int = int(os.getenv("HTTP_PORT", "8090"))
    fhir_timeout_s: float = float(os.getenv("FHIR_TIMEOUT_S", "15"))
    # Identity this service uses in MSH-3/MSH-4 of the ACKs it sends.
    receiving_app: str = os.getenv("RECEIVING_APP", "SIU2FHIR")
    receiving_facility: str = os.getenv("RECEIVING_FACILITY", "POC")

    @property
    def default_tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.default_tz_name)
        except ZoneInfoNotFoundError:
            raise RuntimeError(
                f"Time zone {self.default_tz_name!r} not found. On Windows install the time zone "
                "database: pip install -r requirements.txt  (or: pip install tzdata)") from None
