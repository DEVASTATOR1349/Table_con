"""
Тополь Scheduler — APScheduler каждые 5 минут.
Engine сам сохраняет стейт в /app/logs/state.json после каждого цикла.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from engine import SheetsClient, TopolEngine
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol-scheduler")

INTERVAL_MINUTES = 10

def run_cycle():
    try:
        client = SheetsClient()
        engine = TopolEngine(client)
        engine.run_cycle()
    except Exception as e:
        log.error("Cycle crashed: {}".format(e))


def main():
    log.info("TOPOL scheduler starting (every {} min)".format(INTERVAL_MINUTES))
    db.ensure_tables()
    scheduler = BlockingScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_cycle, "interval", minutes=INTERVAL_MINUTES, next_run_time=datetime.now())
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("TOPOL stopped")


if __name__ == "__main__":
    main()
