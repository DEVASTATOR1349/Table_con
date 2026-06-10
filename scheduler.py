"""
Тополь Scheduler — APScheduler каждые 5 минут + лог в БД
"""

import logging, io
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from engine import SheetsClient, TopolEngine
from config import SHEETS, WORKFLOW
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol-scheduler")

INTERVAL_MINUTES = 5

def run_cycle():
    try:
        client = SheetsClient()
        engine = TopolEngine(client)

        # Collect log lines
        import io
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.INFO)
        log.addHandler(handler)
        
        engine.run_cycle()
        
        log.removeHandler(handler)
        log_lines = log_stream.getvalue().strip().split("\n")[-30:]

        # Scan tables for state
        tables_state = []
        scan_map = [
            ("nomos_scenarios", "Номос", "Номос Сценарии"),
            ("montage_reference", "СценарииСбор", "Спр_Монтаж"),
            ("ai4_report", "Сценарии", "AI4 отчёт"),
            ("montager_mikhail", "ЗаданияV2", "Монтажёр Михаил"),
        ]
        for tk, tn, label in scan_map:
            try:
                sid = SHEETS[tk]["id"]
                h = client._get_headers(sid, tn)
                rows = client.get_recent_rows(sid, tn)
                tables_state.append({
                    "label": label, "tab": tn, "cols": len(h),
                    "last_row": rows[-1]["_row"] if rows else "—",
                    "total_rows": "~" + str(rows[-1]["_row"] if rows else 0),
                    "scanned": len(rows),
                })
            except Exception as e:
                tables_state.append({"label": label, "tab": tn, "cols": "?", "last_row": "?", "total_rows": "?", "scanned": "?", "error": str(e)[:100]})

        # Scan steps
        steps_state = []
        for step in WORKFLOW["steps"]:
            try:
                changes = engine.scan_step(step)
                steps_state.append({"id": step["id"], "name": step["name"], "source": step["trigger"]["source_tab"], "target": step.get("target", "—"), "count": len(changes)})
            except:
                steps_state.append({"id": step["id"], "name": step["name"], "source": "?", "target": "?", "count": 0})

        # Save to UI
        import requests
        try:
            requests.post("http://127.0.0.1:18889/api/state/save", json={
                "tables": tables_state, "steps": steps_state, "logs": log_lines,
            }, timeout=10)
        except:
            pass

    except Exception as e:
        log.error("Cycle crashed: {}".format(e))


def main():
    log.info("TOPOL scheduler starting (every {} min)".format(INTERVAL_MINUTES))
    scheduler = BlockingScheduler(timezone="Europe/Moscow")

    # Первый запуск через 5 секунд после старта, потом каждые N минут
    scheduler.add_job(run_cycle, "interval", minutes=INTERVAL_MINUTES, next_run_time=datetime.now())

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("TOPOL stopped")


if __name__ == "__main__":
    main()
