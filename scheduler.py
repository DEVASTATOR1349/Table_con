"""
Тополь Scheduler — APScheduler каждые 5 минут.
Engine сам сохраняет стейт в /app/logs/state.json после каждого цикла.
"""

import os
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from engine import SheetsClient, TopolEngine
import backfill
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol-scheduler")

INTERVAL_MINUTES = int(os.environ.get("TOPOL_INTERVAL_MINUTES", "10"))
# До-наполнение недостающих строк — отдельная редкая задача (по умолчанию раз в час).
BACKFILL_MINUTES = int(os.environ.get("TOPOL_BACKFILL_MINUTES", "60"))

def run_cycle():
    try:
        client = SheetsClient()
        engine = TopolEngine(client)
        engine.run_cycle()
    except Exception as e:
        log.error("Cycle crashed: {}".format(e))


def run_backfill_job():
    try:
        backfill.run_backfill()
    except Exception as e:
        log.error("Backfill crashed: {}".format(e))


def main():
    log.info("TOPOL scheduler starting (cycle every {} min, backfill every {} min)".format(
        INTERVAL_MINUTES, BACKFILL_MINUTES))
    db.ensure_tables()
    scheduler = BlockingScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_cycle, "interval", minutes=INTERVAL_MINUTES,
                      next_run_time=datetime.now(), max_instances=1, coalesce=True)
    # Первый backfill — через 2 минуты после старта (после первого цикла), затем раз в час.
    scheduler.add_job(run_backfill_job, "interval", minutes=BACKFILL_MINUTES,
                      next_run_time=datetime.now() + timedelta(minutes=2),
                      max_instances=1, coalesce=True)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("TOPOL stopped")


if __name__ == "__main__":
    main()
