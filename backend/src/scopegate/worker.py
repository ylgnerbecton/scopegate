"""One bounded durable delivery loop; SIGTERM drains the current attempt."""

import logging
import os
import signal
import threading

from scopegate.config import get_settings
from scopegate.db import get_engine
from scopegate.services.delivery import process_batch, purge


def main() -> None:
    get_settings()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    logger = logging.getLogger("scopegate.worker")
    logging.basicConfig(level=logging.INFO)
    owner = f"worker:{os.getpid()}"
    while not stopped.is_set():
        try:
            result = process_batch(owner, limit=1)
            if any(result.values()):
                logger.info("delivery_batch %s", result)
            purge()
        except Exception:
            logger.error("delivery_cycle_failed")
        stopped.wait(1)
    get_engine().dispose()


if __name__ == "__main__":
    main()
