"""
Тополь — Table Sync Engine v2
Автоматическая синхронизация между Google Sheets.
Динамическая маршрутизация заданий монтажёрам.
"""

import os, json, time, logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import SHEETS, WORKFLOW, MONTAGER_SHEETS, MONTAGER_ALIASES
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol")

# Сколько последних строк сканировать. Узкое окно = быстро + старые строки
# (выше окна) НЕ читаются и НЕ трогаются: работаем только по свежим/в работе.
SCAN_ROWS = int(os.environ.get("TOPOL_SCAN_ROWS", "30"))
MAX_ROWS_PER_SCAN = SCAN_ROWS  # back-compat alias
HEADER_CACHE = {}
STATE_FILE = "/app/logs/state.json"

# --- Safety guards -------------------------------------------------------
# DRY_RUN: when on, the engine logs every write it WOULD do but never touches
# a sheet. Default ON — must be explicitly disabled to write to production.
DRY_RUN = os.environ.get("TOPOL_DRY_RUN", "1").strip().lower() not in ("0", "false", "no", "off", "")
# Circuit breaker: hard ceiling on writes (cell updates + appends) per cycle.
# A bulk import that tries to fan thousands of changes out (the Step-0
# incident: 6038 montager assignments) trips this and aborts the cycle.
MAX_WRITES_PER_CYCLE = int(os.environ.get("TOPOL_MAX_WRITES", "50"))


class CircuitBreakerTripped(Exception):
    """Raised when a single cycle exceeds MAX_WRITES_PER_CYCLE. Aborts the cycle."""

MONTAGER_TAB = "ЗаданияV2"  # Единый таб для всех монтажёров

COLLECTOR_SHEET_ID = SHEETS["montage_reference"]["id"]
COLLECTOR_TAB = "МонтажерыРаспределение"

# Системные табы — пропускаем при сканировании клиентских
SYSTEM_TABS = {
    "Обзор","Обучение","БазаДанных","РасчетЗП","ОтчетныйЛист",
    "СценарииСбор","СценарииV2М","Лист61","СценарииV3",
    "ПублицистыV3","ПарсПублицистов","СпрКлиент","СпрКлиентСцен",
    "МонтжерыV2М","МонтажерыРаспределение",
}


def rate_limit(wait_mult=1.0):
    if not hasattr(rate_limit, "_last"):
        rate_limit._last = 0
    gap = 1.1 * wait_mult
    elapsed = time.time() - rate_limit._last
    if elapsed < gap:
        time.sleep(gap - elapsed)
    rate_limit._last = time.time()


def api_call(fn, *args, max_retries=3, **kwargs):
    rate_limit()
    for i in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) and i < max_retries - 1:
                backoff = 2 ** (i + 2)
                log.warning("Rate limit (429), retrying in {}s...".format(backoff))
                rate_limit._last = time.time()
                time.sleep(backoff)
                continue
            raise


class SheetsClient:
    def __init__(self, creds_file="service_account.json"):
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self.svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.dry_run = DRY_RUN
        self.writes_this_cycle = 0
        if self.dry_run:
            log.warning("DRY_RUN is ON — no writes will reach the sheets. Set TOPOL_DRY_RUN=0 to enable writes.")

    def reset_write_counter(self):
        self.writes_this_cycle = 0

    def _allow_write(self, desc: str) -> bool:
        """Gate every write through the circuit breaker and dry-run flag.

        Returns True if the caller should perform the real API write,
        False if it must be skipped (dry-run). Raises CircuitBreakerTripped
        once the per-cycle write ceiling is exceeded.
        """
        self.writes_this_cycle += 1
        if self.writes_this_cycle > MAX_WRITES_PER_CYCLE:
            raise CircuitBreakerTripped(
                "More than {} writes in one cycle — aborting to prevent runaway. Last: {}".format(
                    MAX_WRITES_PER_CYCLE, desc)
            )
        if self.dry_run:
            log.info("  [DRY-RUN] would write: {}".format(desc))
            return False
        return True

    def _resolve(self, path: str):
        """Разбирает 'table_key/tab_key' -> (sheet_id, tab_name)"""
        table_key, tab_key = path.split("/")
        for tk, v in SHEETS.items():
            if tk == table_key:
                return v["id"], v["tabs"].get(tab_key, tab_key)
        raise ValueError("Unknown table: " + table_key)

    def _get_headers(self, sheet_id: str, tab_name: str) -> dict:
        """Возвращает {normalized_name: col_idx}, кешируется."""
        key = (sheet_id, tab_name)
        if key in HEADER_CACHE:
            return HEADER_CACHE[key]
        rate_limit()
        rng = "'{}'!A1:ZZ1".format(tab_name)
        r = api_call(lambda: self.svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute())
        rows = r.get("values", [])
        hdrs = {}
        if rows:
            for i, h in enumerate(rows[0]):
                raw = str(h).strip()
                import re
                norm = re.sub(r'\s*\d+\s*$', '', raw)
                norm = re.sub(r'\s+', ' ', norm).strip()
                if norm:
                    current = hdrs.get(norm)
                    if current is None or len(raw) > len(str(rows[0][current]).strip()):
                        hdrs[norm] = i
        HEADER_CACHE[key] = hdrs
        return hdrs

    def _col_letter(self, n: int) -> str:
        result = ""
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    def get_recent_rows(self, sheet_id: str, tab_name: str, limit: int = MAX_ROWS_PER_SCAN) -> List[Dict]:
        """Читает последние N строк (снизу)."""
        headers = self._get_headers(sheet_id, tab_name)
        if not headers:
            return []

        # Дешёвый подсчёт числа строк: колонка A, обрезанная до последней
        # непустой. Раньше ради подсчёта тянулся весь rowData листа
        # (userEnteredValue) — медленно. Допущение: колонка A заполнена у каждой
        # строки с данными (в этих таблицах это ID/дата/проект).
        rate_limit()
        colA = api_call(lambda: self.svc.spreadsheets().values().get(
            spreadsheetId=sheet_id, range="'{}'!A:A".format(tab_name)).execute())
        total = len(colA.get("values", []))
        if total < 2:
            return []

        start = max(2, total - limit + 1)
        # Header indices come from the full A1:ZZ1 row, so the read range must
        # span up to the largest mapped index — NOT len(headers). Using the
        # count drops the rightmost columns whenever any header cell is blank
        # or two headers collapse to one normalized name.
        max_idx = max(headers.values()) if headers else 0
        end_col = self._col_letter(max_idx + 1)
        rng = "'{}'!A{}:{}{}".format(tab_name, start, end_col, total)
        r = api_call(lambda: self.svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute())
        rows = r.get("values", [])
        result = []
        for ri, row in enumerate(rows):
            rd = {"_row": start + ri}
            for h, ci in headers.items():
                rd[h] = row[ci] if ci < len(row) else ""
            result.append(rd)
        return result

    def update_cell(self, sheet_id: str, tab_name: str, row: int, col: int, value: str):
        col_letter = self._col_letter(col + 1)
        rng = "'{}'!{}{}".format(tab_name, col_letter, row)
        if not self._allow_write("update {} {} = {!r}".format(tab_name, rng, str(value)[:60])):
            return
        body = {"values": [[value]]}
        api_call(lambda: self.svc.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=rng, body=body, valueInputOption="USER_ENTERED"
        ).execute())

    def update_row(self, sheet_id: str, tab_name: str, row: int, values: dict):
        headers = self._get_headers(sheet_id, tab_name)
        for col_name, val in values.items():
            if col_name in headers:
                self.update_cell(sheet_id, tab_name, row, headers[col_name], val)

    def append_row(self, sheet_id: str, tab_name: str, values: list):
        if not self._allow_write("append to {} : {}".format(tab_name, values)):
            return
        body = {"values": [values]}
        api_call(lambda: self.svc.spreadsheets().values().append(
            spreadsheetId=sheet_id, range="'" + tab_name + "'!A1",
            body=body, valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS"
        ).execute())

    def find_row_by_field(self, sheet_id: str, tab_name: str, field: str, value: str) -> tuple:
        """Ищет строку по значению поля. Возвращает (row_dict, row_number) или (None, None)."""
        rows = self.get_recent_rows(sheet_id, tab_name)
        for rd in rows:
            if str(rd.get(field, "")).strip() == str(value).strip():
                return rd, rd["_row"]
        return None, None


class TopolEngine:
    def __init__(self, client: SheetsClient):
        self.client = client

    def scan_step(self, step: dict) -> list:
        trigger = step["trigger"]
        source_path = trigger["source_tab"]
        action = step["action"]

        # Step 6: сканируем ВСЕХ доступных монтажёров
        if action == "sync_montager_bidirectional":
            return self._scan_montagers_for_changes(step)

        if action == "import_client_tabs":
            return [{"row": {"_row": "all"}, "step": step}]

        sid, tab = self.client._resolve(source_path)

        try:
            rows = self.client.get_recent_rows(sid, tab)
        except Exception as e:
            log.warning("Step {}: cannot read {}: {}".format(step["id"], source_path, e))
            return []

        changes = []
        skipped = 0
        for rd in rows:
            if self._check_trigger(rd, trigger):
                rn = str(rd.get("_row", ""))
                trigger_fields = self._trigger_fields(trigger)
                if db.is_processed(step["id"], rn, rd, trigger_fields):
                    skipped += 1
                    continue
                changes.append({"row": rd, "step": step})
        if skipped:
            log.info("  Step {}: {} skipped (already processed)".format(step["id"], skipped))
        return changes

    def _scan_montagers_for_changes(self, step: dict) -> list:
        """Сканирует ЗаданияV2 всех доступных монтажёров на изменения статуса/комментария."""
        changes = []
        fields_to_sync = step["trigger"].get("fields", [])
        skipped = 0
        accessible = sum(1 for m in MONTAGER_SHEETS.values() if m.get("access", False))

        for mname, minfo in MONTAGER_SHEETS.items():
            if not minfo.get("access", False):
                continue
            try:
                rows = self.client.get_recent_rows(minfo["id"], MONTAGER_TAB, limit=SCAN_ROWS)
            except Exception as e:
                log.debug("  Cannot read {} ({}): {}".format(mname, minfo["id"], str(e)[:80]))
                continue

            for rd in rows:
                row_id = str(rd.get("ID", "")).strip()
                if not row_id:
                    continue

                has_data = False
                for f in fields_to_sync:
                    val = str(rd.get(f, "")).strip()
                    if val and val not in ("—", "-", ""):
                        has_data = True
                        break
                if not has_data:
                    continue

                # Дедупликация: уникальный ключ = mname:row_id
                dedup_key = "{}:{}".format(mname, row_id)
                mini_row = {f: str(rd.get(f, "")) for f in fields_to_sync}
                if db.is_processed(step["id"], dedup_key, mini_row, fields_to_sync):
                    skipped += 1
                    continue

                changes.append({
                    "row": rd,
                    "step": step,
                    "montager_name": mname,
                    "montager_sid": minfo["id"],
                    "dedup_key": dedup_key,
                })

        log.info("  Montager scan: {} new changes ({} skipped) across {} accessible montagers".format(
            len(changes), skipped, accessible))
        return changes

    def _trigger_fields(self, trigger: dict) -> list:
        fields = []
        if trigger.get("status_col"):
            fields.append(trigger["status_col"])
        f = trigger.get("fields", [])
        if isinstance(f, dict):
            fields.extend(f.keys())
        elif isinstance(f, list):
            fields.extend(f)
        return fields

    def _check_trigger(self, row: dict, trigger: dict) -> bool:
        sc = trigger.get("status_col")
        sv = trigger.get("value")
        fields = trigger.get("fields", [])
        cond = trigger.get("conditions", "ANY")

        if sc:
            actual = str(row.get(sc, "")).strip()
            expected = str(sv).strip() if sv else ""
            if sv == "filled":
                if not actual or actual in ("—", "-", ""):
                    return False
            elif actual != expected:
                return False

        if fields:
            if isinstance(fields, dict):
                results = []
                for col, expected in fields.items():
                    actual = str(row.get(col, "")).strip()
                    if str(expected).strip() == "filled":
                        results.append(bool(actual and actual not in ("—", "-", "")))
                    else:
                        results.append(actual == str(expected).strip())
                return all(results) if cond == "ALL" else any(results)
            else:
                results = []
                for col in fields:
                    val = str(row.get(col, "")).strip()
                    results.append(bool(val and val not in ("—", "-", "")))
                return all(results) if cond == "ALL" else any(results)

        return True if (sc or fields) else False

    def execute_step(self, changes: list) -> int:
        count = 0
        for ch in changes:
            step = ch["step"]
            row = ch["row"]
            action = step["action"]
            src = step["trigger"]["source_tab"]
            tgt = step.get("target", "—")

            try:
                if action in ("copy_to_client", "send_to_client"):
                    self._copy_to_target(row, step)
                elif action == "sync_bidirectional":
                    self._sync_fields(row, step)
                elif action == "assign_to_montager":
                    self._assign_montager(row, step)
                elif action == "sync_montager_bidirectional":
                    mname = ch.get("montager_name", "?")
                    msid = ch.get("montager_sid", "")
                    self._sync_from_montager(row, mname, msid, step)
                    # Логируем с уникальным dedup_key
                    trigger_fields = self._trigger_fields(step["trigger"])
                    db.log_sync(step["id"], action, src, tgt,
                        ch.get("dedup_key", "unknown"),
                        "Montager {}: ID {}".format(mname, row.get("ID", "")),
                        row=row, fields=trigger_fields)
                    count += 1
                    continue  # skip generic log below
                elif action == "send_to_scenarist":
                    self._send_to_scenarist(row, step)
                elif action == "update_client_table":
                    self._update_client(row, step)

                elif action == "notify_manager":
                    log.info("  [NOTIFY] Row {} ready for montage".format(row.get("_row")))

                # Generic SQL log (not for montager_bidirectional — handled above)
                trigger_fields = self._trigger_fields(step["trigger"])
                db.log_sync(step["id"], action, src, tgt, row.get("_row", 0),
                    "Row {}: {}".format(row.get("_row"), row.get("ID", row.get("Проект", ""))),
                    row=row, fields=trigger_fields)
                self._sql_upsert(row, src)

                count += 1
            except CircuitBreakerTripped:
                # Do not swallow — propagate up to abort the whole cycle.
                raise
            except Exception as e:
                log.error("  Step {} failed on row {}: {}".format(step["id"], row.get("_row"), e))
                db.log_sync(step["id"], action, src, tgt, row.get("_row", 0), str(e)[:500], "error")

        return count

    def _sql_upsert(self, row: dict, source_path: str):
        if "nomos_scenarios" in source_path or "main" in source_path or "Номос" in source_path:
            sid, tab = self.client._resolve(source_path)
            db.upsert_scenario(row, sid, tab)
        elif "montage_reference" in source_path or "СценарииСбор" in source_path or "Монтаж" in source_path:
            sid, tab = self.client._resolve(source_path)
            db.upsert_montage(row, sid, tab)

    def _copy_to_target(self, row: dict, step: dict):
        target_path = step["target"]
        sid, tab = self.client._resolve(target_path)
        headers = self.client._get_headers(sid, tab)
        vals = {}
        for h in headers:
            if h in row:
                vals[h] = str(row[h])
        log.info("  Copy {} fields to {} row {}...".format(len(vals), tab, row.get("_row")))

    def _sync_fields(self, row: dict, step: dict):
        fields = step["trigger"].get("fields", [])
        target_path = step["target"]
        sid, tab = self.client._resolve(target_path)
        row_id = row.get("ID", row.get("id", ""))
        if not row_id:
            return
        tr, tn = self.client.find_row_by_field(sid, tab, "ID", row_id)
        if tr:
            updates = {}
            for f in fields:
                if f in row:
                    updates[f] = str(row[f])
            if updates:
                self.client.update_row(sid, tab, tn, updates)
                log.info("  Synced {} fields to {} row {}".format(len(updates), tab, tn))

    def _assign_montager(self, row: dict, step: dict):
        """Динамическая маршрутизация задания к монтажёру по имени из 'Выбор монтажера'."""
        mn = str(row.get("Выбор монтажера", "")).strip()
        if not mn:
            return

        mn_key = mn.replace(" ", "")

        # Алиас
        if mn_key in MONTAGER_ALIASES:
            mn_key = MONTAGER_ALIASES[mn_key]

        now_str = datetime.now().strftime("%d.%m.%Y")
        row_data = [
            now_str,
            str(row.get("ID", "")),
            str(row.get("Проект", "")),
            mn,
        ]

        row_id = str(row.get("ID", "")).strip()

        if mn_key in MONTAGER_SHEETS:
            minfo = MONTAGER_SHEETS[mn_key]
            if minfo.get("access", False):
                # Idempotency guard: never append a task whose ID is already in
                # the montager's sheet. This is a second line of defence on top
                # of the DB dedup — if PostgreSQL is unreachable, is_processed()
                # returns False and the old code would re-append every cycle.
                if row_id and self._montager_has_id(minfo["id"], row_id):
                    log.info("  ⏭ {} → {}: ID {} уже есть, пропуск".format(mn, mn_key, row_id))
                    return
                self.client.append_row(minfo["id"], MONTAGER_TAB, row_data)
                log.info("  ➡ {} → {} (ID {})".format(mn, mn_key, row.get("ID", "?")))
                return
            else:
                log.warning("  ⚠ {}: нет доступа, пишу в коллектор".format(mn))
        else:
            log.warning("  ⚠ {}: нет в MONTAGER_SHEETS, пишу в коллектор".format(mn))

        if row_id and self._collector_has_id(row_id):
            log.info("  ⏭ коллектор: ID {} уже есть, пропуск".format(row_id))
            return
        self.client.append_row(COLLECTOR_SHEET_ID, COLLECTOR_TAB, row_data)
        log.info("  📋 {} → коллектор".format(mn))

    def _montager_has_id(self, sheet_id: str, row_id: str) -> bool:
        try:
            tr, _ = self.client.find_row_by_field(sheet_id, MONTAGER_TAB, "ID", row_id)
            return tr is not None
        except Exception as e:
            # On read failure, refuse to append rather than risk a duplicate.
            log.warning("  Cannot verify montager sheet for ID {}: {} — skipping append".format(row_id, str(e)[:80]))
            return True

    def _collector_has_id(self, row_id: str) -> bool:
        try:
            tr, _ = self.client.find_row_by_field(COLLECTOR_SHEET_ID, COLLECTOR_TAB, "ID", row_id)
            return tr is not None
        except Exception as e:
            log.warning("  Cannot verify collector for ID {}: {} — skipping append".format(row_id, str(e)[:80]))
            return True

    def _sync_from_montager(self, row: dict, mname: str, msid: str, step: dict):
        """Синхронизирует поля из таблицы монтажёра обратно в СценарииСбор."""
        fields = step["trigger"].get("fields", [])
        ref_sid = SHEETS["montage_reference"]["id"]
        ref_tab = "СценарииСбор"
        row_id = str(row.get("ID", "")).strip()
        if not row_id:
            return

        tr, tn = self.client.find_row_by_field(ref_sid, ref_tab, "ID", row_id)
        if tr:
            updates = {}
            for f in fields:
                if f in row:
                    val = str(row.get(f, "")).strip()
                    if val:
                        updates[f] = val
            if updates:
                self.client.update_row(ref_sid, ref_tab, tn, updates)
                log.info("  🔄 {} → reference: {} fields for ID {}".format(mname, len(updates), row_id))
        else:
            log.debug("  ID {} not found in reference table".format(row_id))

    def _send_to_scenarist(self, row: dict, step: dict):
        target_path = step["target"]
        sid, tab = self.client._resolve(target_path)
        link = row.get("Ссылка с Готовым материалом", "")
        if link:
            tr, tn = self.client.find_row_by_field(sid, tab, "ID", str(row.get("ID", "")))
            if tr:
                self.client.update_row(sid, tab, tn, {
                    "Ссылка с Готовым материалом": link,
                    "Одобрение клиента": str(row.get("Одобрение клиента", "")),
                })
                log.info("  Sent montage link to scenarist")

    def _update_client(self, row: dict, step: dict):
        target_path = step["target"]
        sid, tab = self.client._resolve(target_path)
        tr, tn = self.client.find_row_by_field(sid, tab, "ID", str(row.get("ID", "")))
        if tr:
            self.client.update_row(sid, tab, tn, {
                "Дата Готового монтажа": str(row.get("Дата Готового монтажа", "")),
                "Описание": str(row.get("Описание", "")),
            })
            log.info("  Updated client table")


    def run_cycle(self):
        log.info("=" * 50)
        log.info("TOPOL cycle: " + datetime.now().isoformat())
        if self.client.dry_run:
            log.warning("DRY_RUN ON — writes are simulated only.")
        self.client.reset_write_counter()
        self._cycle_logs = []
        total = 0
        steps_result = []
        for step in WORKFLOW["steps"]:
            try:
                changes = self.scan_step(step)
                count = len(changes)
                if changes:
                    log.info("Step {}: {} — {} rows".format(step["id"], step["name"], count))
                    n = self.execute_step(changes)
                    total += n
                    msg = "Step {}: {} — {} rows, {} actions".format(step["id"], step["name"], count, n)
                else:
                    msg = "Step {}: {} — no hits".format(step["id"], step["name"])
                self._cycle_logs.append(msg)
                steps_result.append({
                    "id": step["id"], "name": step["name"],
                    "source": step["trigger"]["source_tab"],
                    "target": step.get("target", "—"), "count": count,
                })
            except CircuitBreakerTripped as e:
                log.error("!! CIRCUIT BREAKER: {}".format(e))
                log.error("!! Cycle ABORTED after {} writes. Investigate before re-running.".format(
                    self.client.writes_this_cycle))
                self._cycle_logs.append("CIRCUIT BREAKER tripped at step {}: {}".format(step["id"], e))
                db.log_sync(step["id"], "circuit_breaker", "—", "—", 0, str(e)[:500], "error")
                break
            except Exception as e:
                log.error("Step {} ERROR: {}".format(step["id"], e))
                steps_result.append({
                    "id": step["id"], "name": step["name"],
                    "source": "?", "target": "?", "count": 0,
                })
        log.info("Cycle done: {} actions".format(total))
        self._save_state(steps_result)
        return steps_result

    def _save_state(self, steps_result):
        try:
            tables_state = []
            scan_map = [
                ("nomos_scenarios", "Номос", "Номос Сценарии"),
                ("montage_reference", "СценарииСбор", "Спр_Монтаж"),
                ("ai4_report", "Сценарии", "AI4 отчёт"),
            ]
            for tk, tn, label in scan_map:
                try:
                    sid = SHEETS[tk]["id"]
                    h = self.client._get_headers(sid, tn)
                    rows = self.client.get_recent_rows(sid, tn)
                    tables_state.append({
                        "label": label, "tab": tn, "cols": len(h),
                        "last_row": rows[-1]["_row"] if rows else "—",
                        "total_rows": "~" + str(rows[-1]["_row"] if rows else 0),
                        "scanned": len(rows),
                    })
                except Exception as e:
                    tables_state.append({"label": label, "tab": tn, "cols": "?", "last_row": "?", "total_rows": "?", "scanned": "?", "error": str(e)[:100]})

            os.makedirs("/app/logs", exist_ok=True)
            json.dump({
                "tables": tables_state, "steps": steps_result,
                "logs": getattr(self, "_cycle_logs", []),
                "ts": datetime.now().isoformat(),
            }, open(STATE_FILE, "w"), indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning("State save failed: {}".format(e))


def main():
    client = SheetsClient()
    engine = TopolEngine(client)
    log.info("TOPOL started")
    for name, cfg in SHEETS.items():
        log.info("  {}: {} ({} tabs)".format(name, cfg["description"], len(cfg["tabs"])))
    engine.run_cycle()


if __name__ == "__main__":
    main()
