"""
backfill.py — почасовое до-наполнение СценарииСбор недостающими строками.

Зачем: главный цикл движка быстрый и смотрит только последние TOPOL_SCAN_ROWS
строк. Если в СценарииСбор каких-то строк нет (есть в клиентских табах, но не
в сводном листе) — этот фон раз в час их подтягивает.

КАК это сделано безопасно (в отличие от рокового Step 0):
  * Мэппинг колонок ПО ИМЕНИ, не по позиции (ничего не съезжает).
  * Дедуп по ID: добавляются только строки, которых ещё нет в СценарииСбор.
  * Добавленные строки СРАЗУ помечаются в dedup (sync_log) как «обработанные»
    для шагов, стартующих из СценарииСбор (в т.ч. Step 5 assign_to_montager).
    => импорт НЕ вызывает массовую рассылку монтажёрам. Движок отреагирует
    только на БУДУЩИЕ реальные изменения этих строк.
  * Уважает TOPOL_DRY_RUN (по умолчанию только логирует, не пишет).
  * Потолок TOPOL_BACKFILL_MAX на число строк за один прогон — флуд не пройдёт
    молча: лог предупреждает, остаток подтянется в следующие часы.

Запуск разово:  docker exec topol-engine python3 /app/backfill.py
Планировщик:    см. scheduler.py (job каждые TOPOL_BACKFILL_MINUTES минут).
"""

import sys, os, logging
sys.path.insert(0, "/app")

from engine import SheetsClient, api_call
from config import WORKFLOW
from restore_scenariisbor import REF_ID, TARGET_TAB, ID_HEADER, list_client_tabs, build_row
import db

log = logging.getLogger("topol-backfill")

# Полный лист читаем целиком (раз в час — можно), чтобы знать ВСЕ существующие ID
# и не задублировать строки, лежащие выше окна сканирования движка.
FULL_SCAN = int(os.environ.get("TOPOL_BACKFILL_SCAN", "5000"))
# Потолок добавлений за один прогон. Большой бэклог сливается за несколько часов.
BACKFILL_MAX = int(os.environ.get("TOPOL_BACKFILL_MAX", "200"))
APPEND_CHUNK = 100

# Источник сводного листа в config — это "montage_reference/scenarios".
COLLECTION_SRC = "montage_reference/scenarios"


def _trigger_fields(trigger: dict) -> list:
    """Те же поля, по которым движок считает hash дедупа (см. engine._trigger_fields)."""
    fields = []
    if trigger.get("status_col"):
        fields.append(trigger["status_col"])
    f = trigger.get("fields", [])
    if isinstance(f, dict):
        fields.extend(f.keys())
    elif isinstance(f, list):
        fields.extend(f)
    return fields


def _steps_from_collection() -> list:
    """Шаги, которые стартуют из СценарииСбор и дедупятся по номеру строки.

    Исключаем sync_montager_bidirectional — у него дедуп по ключу mname:ID,
    а не по _row, и стартует он со сканирования таблиц монтажёров.
    """
    out = []
    for step in WORKFLOW["steps"]:
        if step["trigger"]["source_tab"] == COLLECTION_SRC and step["action"] != "sync_montager_bidirectional":
            out.append(step)
    return out


def _append_chunked(client: SheetsClient, rows_arr: list):
    for i in range(0, len(rows_arr), APPEND_CHUNK):
        chunk = rows_arr[i:i + APPEND_CHUNK]
        body = {"values": chunk}
        api_call(lambda: client.svc.spreadsheets().values().append(
            spreadsheetId=REF_ID, range="'" + TARGET_TAB + "'!A1",
            body=body, valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS"
        ).execute())


def _seed_dedup(client: SheetsClient, new_ids: set):
    """Помечает только что добавленные строки как обработанные на их ТЕКУЩЕМ
    состоянии — чтобы движок не сработал на них сейчас, только на будущие правки."""
    steps = _steps_from_collection()
    if not steps or not new_ids:
        return
    rows = client.get_recent_rows(REF_ID, TARGET_TAB, limit=FULL_SCAN)
    seeded = 0
    for rd in rows:
        rid = str(rd.get(ID_HEADER, "")).strip()
        if rid not in new_ids:
            continue
        rn = rd.get("_row", 0)
        for step in steps:
            tf = _trigger_fields(step["trigger"])
            db.log_sync(step["id"], "backfill_seed", COLLECTION_SRC, step.get("target", "—"),
                        rn, "seed import ID {}".format(rid), row=rd, fields=tf, status="ok")
            seeded += 1
    log.info("backfill: seeded dedup for %d rows x %d steps (%d records)",
             len(new_ids), len(steps), seeded)


def run_backfill():
    client = SheetsClient()
    target_headers = client._get_headers(REF_ID, TARGET_TAB)
    if not target_headers:
        log.warning("backfill: target headers empty, abort")
        return 0

    # ВСЕ существующие ID в сводном листе (полное чтение, не окно).
    existing = {str(r.get(ID_HEADER, "")).strip()
                for r in client.get_recent_rows(REF_ID, TARGET_TAB, limit=FULL_SCAN)
                if str(r.get(ID_HEADER, "")).strip()}

    seen = set(existing)
    missing = []  # [(id, row_dict)]
    for tab in list_client_tabs(client):
        try:
            rows = client.get_recent_rows(REF_ID, tab, limit=FULL_SCAN)
        except Exception as e:
            log.warning("backfill: cannot read %s: %s", tab, str(e)[:80])
            continue
        for rd in rows:
            rid = str(rd.get(ID_HEADER, "")).strip()
            if not rid or rid in seen:
                continue
            seen.add(rid)
            missing.append((rid, rd))

    if not missing:
        log.info("backfill: nothing missing (%d existing IDs)", len(existing))
        return 0

    capped = len(missing) > BACKFILL_MAX
    if capped:
        log.warning("backfill: %d missing > cap %d — importing first %d, rest next runs",
                    len(missing), BACKFILL_MAX, BACKFILL_MAX)
        missing = missing[:BACKFILL_MAX]

    arrs = [build_row(rd, target_headers) for _, rd in missing]

    if client.dry_run:
        log.info("[DRY-RUN] backfill would add %d rows to %s (capped=%s)",
                 len(arrs), TARGET_TAB, capped)
        for rid, rd in missing[:5]:
            log.info("  [DRY-RUN] would add ID %s (%s)", rid, str(rd.get("Проект", ""))[:40])
        return 0

    _append_chunked(client, arrs)
    log.info("backfill: added %d rows to %s", len(arrs), TARGET_TAB)
    _seed_dedup(client, {rid for rid, _ in missing})
    return len(arrs)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    n = run_backfill()
    print("backfill done: {} rows".format(n))
