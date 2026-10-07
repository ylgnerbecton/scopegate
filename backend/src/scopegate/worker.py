"""One bounded durable delivery loop; SIGTERM drains the current attempt."""

import logging
import os
import signal
import time

from scopegate import telemetry
from scopegate.config import get_settings
from scopegate.db import get_engine
from scopegate.services.delivery import process_batch, purge


def main() -> None:
    stopping = False

    def stop(*_args: object) -> None:
        # Signal handlers must not acquire locks held by the interrupted thread.
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    get_settings()
    telemetry.initialize()
    logger = logging.getLogger("scopegate.worker")
    logging.basicConfig(level=logging.INFO)
    owner = f"worker:{os.getpid()}"
    while not stopping:
        try:
            result = process_batch(owner, limit=1)
            if any(result.values()):
                logger.info("delivery_batch %s", result)
            purge()
        except Exception:
            logger.error("delivery_cycle_failed")
        for _ in range(10):
            if stopping:
                break
            time.sleep(0.1)
    get_engine().dispose()
    telemetry.flush()


if __name__ == "__main__":
    main()
