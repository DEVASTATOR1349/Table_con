"""
Тополь — Table Sync Engine v2
Автоматическая синхронизация между 4 таблицами Google Sheets.
Оптимизировано для больших таблиц (лимит строк, кеш заголовков).
"""

import os, json, time, logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import SHEETS, WORKFLOW
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol")

MAX_ROWS_PER_SCAN = 500
HEADER_CACHE = {}
STATE_FILE = "/app/logs/state.json"


def rate_limit(wait_mult=1.0):
    if not hasattr(rate_limit, "_last"):
        rate_limit._last = 0
    gap = 1.1 * wait_mult
    elapsed = time.time() - rate_limit._last
    if elapsed < gap:
        time.sleep(gap - elapsed)
    rate_limit._last = time.time()


def api_call(fn, *args, max_retries=3, **kwargs):
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
        r = self.svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute()
        rows = r.get("values", [])
        hdrs = {}
        if rows:
            for i, h in enumerate(rows[0]):
                raw = str(h).strip()
                # Normalize: remove trailing numbers, collapse whitespace/newlines
                import re
                norm = re.sub(r'\s*\d+\s*$', '', raw)  # strip trailing number
                norm = re.sub(r'\s+', ' ', norm).strip()  # collapse spaces/newlines
                if norm:
                    # Always store by normalized name, allowing overwrite by explicit match
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
        """Читает последние N строк (снизу). Быстро даже для таблиц на 16K строк."""
        headers = self._get_headers(sheet_id, tab_name)
        if not headers:
            return []

        # Сначала узнаём сколько всего строк
        rate_limit()
        meta = self.svc.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=["'" + tab_name + "'"],
            fields="sheets/data/rowData/values/userEnteredValue"
        ).execute()
        sheets_data = meta.get("sheets", [])
        total = len(sheets_data[0].get("data", [{}])[0].get("rowData", [])) if sheets_data else 0

        # Читаем последние limit строк (или все, если их меньше)
        start = max(2, total - limit + 1)
        end_col = self._col_letter(len(headers))
        rng = "'{}'!A{}:{}{}".format(tab_name, start, end_col, total)
        r = self.svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute()
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
        body = {"values": [[value]]}
        rate_limit()
        self.svc.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=rng, body=body, valueInputOption="USER_ENTERED"
        ).execute()

    def update_row(self, sheet_id: str, tab_name: str, row: int, values: dict):
        headers = self._get_headers(sheet_id, tab_name)
        for col_name, val in values.items():
            if col_name in headers:
                self.update_cell(sheet_id, tab_name, row, headers[col_name], val)

    def append_row(self, sheet_id: str, tab_name: str, values: list):
        body = {"values": [values]}
        rate_limit()
        self.svc.spreadsheets().values().append(
            spreadsheetId=sheet_id, range="'" + tab_name + "'!A1",
            body=body, valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS"
        ).execute()

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
                # Dedup: skip if already processed with same hash
                trigger_fields = self._trigger_fields(trigger)
                if db.is_processed(step["id"], rn, rd, trigger_fields):
                    skipped += 1
                    continue
                changes.append({"row": rd, "step": step})
        if skipped:
            log.info("  Step {}: {} skipped (already processed)".format(step["id"], skipped))
        return changes

    def _trigger_fields(self, trigger: dict) -> list:
        """Extract field names from trigger for hashing."""
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
                # dict: {"col": "value_or_filled"} — проверяем точное значение
                results = []
                for col, expected in fields.items():
                    actual = str(row.get(col, "")).strip()
                    if str(expected).strip() == "filled":
                        results.append(bool(actual and actual not in ("—", "-", "")))
                    else:
                        results.append(actual == str(expected).strip())
                return all(results) if cond == "ALL" else any(results)
            else:
                # list: ["col1", "col2"] — проверяем непустоту
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
                elif action == "send_to_scenarist":
                    self._send_to_scenarist(row, step)
                elif action == "update_client_table":
                    self._update_client(row, step)
                elif action == "notify_manager":
                    log.info("  [NOTIFY] Row {} ready for montage".format(row.get("_row")))

                # Write to SQL
                trigger_fields = self._trigger_fields(step["trigger"])
                db.log_sync(step["id"], action, src, tgt, row.get("_row", 0),
                    "Row {}: {}".format(row.get("_row"), row.get("ID", row.get("Проект", ""))),
                    row=row, fields=trigger_fields)
                # Upsert row data into scenarios or montage_tasks
                self._sql_upsert(row, src)

                count += 1
            except Exception as e:
                log.error("  Step {} failed on row {}: {}".format(step["id"], row.get("_row"), e))
                db.log_sync(step["id"], action, src, tgt, row.get("_row", 0), str(e)[:500], "error")

        return count

    def _sql_upsert(self, row: dict, source_path: str):
        """Определить тип по источнику и записать в правильную SQL таблицу."""
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
        target_path = step["target"]
        sid, tab = self.client._resolve(target_path)
        mn = row.get("Выбор монтажера", "")
        if mn:
            self.client.append_row(sid, tab, [
                datetime.now().strftime("%d.%m.%Y"),
                str(row.get("ID", "")),
                str(row.get("Проект", "")),
                mn,
            ])
            log.info("  Assigned to montager: " + mn)

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
                steps_result.append({
                    "id": step["id"], "name": step["name"],
                    "source": step["trigger"]["source_tab"],
                    "target": step.get("target", "—"), "count": count,
                })
            except Exception as e:
                log.error("Step {} ERROR: {}".format(step["id"], e))
                steps_result.append({
                    "id": step["id"], "name": step["name"],
                    "source": "?", "target": "?", "count": 0,
                })
        log.info("Cycle done: {} actions".format(total))

        # Save state for UI (via shared volume)
        self._save_state(steps_result)
        return steps_result

    def _save_state(self, steps_result):
        try:
            import json as j, os
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
            j.dump({
                "tables": tables_state, "steps": steps_result, "ts": datetime.now().isoformat(),
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
