"""Run the SIU -> FHIR service: python -m siu2fhir_au"""
from __future__ import annotations

import logging
import os
import signal
import threading

from .config import Config
from .processor import Processor
from .servers import make_http_server, make_mllp_server


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    processor = Processor(cfg)
    mllp = make_mllp_server(cfg.mllp_host, cfg.mllp_port, processor)
    http = make_http_server(cfg.http_host, cfg.http_port, processor)
    log = logging.getLogger("siu2fhir_au")
    log.info("FHIR server: %s", cfg.fhir_base_url)
    log.info("MLLP listening on %s:%d, HTTP on %s:%d",
             cfg.mllp_host, cfg.mllp_port, cfg.http_host, cfg.http_port)

    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (mllp, http)]
    for t in threads:
        t.start()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    log.info("Shutting down")
    mllp.shutdown()
    http.shutdown()


if __name__ == "__main__":
    main()
