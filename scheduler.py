"""
Тополь Scheduler — запускает engine каждые 5 минут
"""

import time
import signal
import logging
from datetime import datetime
from engine import SheetsClient, TopolEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol-scheduler")

INTERVAL = 300  # 5 минут

def main():
    log.info("ТОПОЛЬ scheduler started (interval: {}s)".format(INTERVAL))
    client = SheetsClient()
    engine = TopolEngine(client)

    running = True
    def handler(sig, frame):
        nonlocal running
        running = False
        log.info("Shutting down...")

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    while running:
        try:
            engine.run_cycle()
        except Exception as e:
            log.error("Cycle failed: {}".format(e))

        for _ in range(INTERVAL):
            if not running:
                break
            time.sleep(1)

    log.info("ТОПОЛЬ stopped")

if __name__ == "__main__":
    main()
