"""
Тополь — Table Sync Engine
Автоматическая синхронизация между 4 таблицами Google Sheets
по цепочке движения видеоконтента.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import SHEETS, WORKFLOW

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("topol")

# === Google Sheets Client ===

class SheetsClient:
    def __init__(self, creds_file="service_account.json"):
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self.svc = build("sheets", "v4", credentials=creds)
        self._sheet_meta = {}  # cache: sid -> {tab_name: {col_name: col_index}}

    def _resolve_tab(self, path: str):
        """Разбирает 'table_key/tab_key' -> (sheet_id, tab_name)"""
        table_key, tab_key = path.split("/")
        # Try short keys first, then iterate
        for tk, v in SHEETS.items():
            if tk == table_key:
                tab_name = v["tabs"].get(tab_key, tab_key)
                return v["id"], tab_name
        raise ValueError(f"Unknown table: {table_key}")

    def get_headers(self, sheet_id: str, tab_name: str) -> List[str]:
        """Получить заголовки таблицы (первая строка)."""
        rng = f"'{tab_name}'!A1:ZZ1"
        r = self.svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute()
        rows = r.get("values", [])
        if not rows:
            return []
        return [str(c).strip() for c in rows[0]]

    def get_all_rows(self, sheet_id: str, tab_name: str, start_row: int = 2) -> List[Dict]:
        """Получить все строки как список словарей {header: value}."""
        headers = self.get_headers(sheet_id, tab_name)
        if not headers:
            return []
        end_col = self._col_letter(len(headers))
        rng = f"'{tab_name}'!A{start_row}:{end_col}"
        r = self.svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute()
        rows = r.get("values", [])
        result = []
        for ri, row in enumerate(rows):
            rd = {"_row": start_row + ri}
            for ci, h in enumerate(headers):
                rd[h] = row[ci] if ci < len(row) else ""
            result.append(rd)
        return result

    def find_row_by_field(self, sheet_id: str, tab_name: str, field: str, value: str, start_row: int = 2):
        """Найти строку по значению в поле. Возвращает (row_dict, row_number)."""
        rows = self.get_all_rows(sheet_id, tab_name, start_row)
        for rd in rows:
            if str(rd.get(field, "")).strip() == str(value).strip():
                return rd, rd["_row"]
        return None, None

    def update_cell(self, sheet_id: str, tab_name: str, row: int, col: int, value: str):
        """Обновить одну ячейку."""
        col_letter = self._col_letter(col + 1)
        rng = f"'{tab_name}'!{col_letter}{row}"
        body = {"values": [[value]]}
        self.svc.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=rng, body=body, valueInputOption="USER_ENTERED"
        ).execute()

    def update_row(self, sheet_id: str, tab_name: str, row: int, values: Dict[str, str]):
        """Обновить несколько ячеек в строке по именам колонок."""
        headers = self.get_headers(sheet_id, tab_name)
        for col_name, val in values.items():
            if col_name in headers:
                col_idx = headers.index(col_name)
                self.update_cell(sheet_id, tab_name, row, col_idx, val)

    def append_row(self, sheet_id: str, tab_name: str, values: List[str]):
        """Добавить строку в конец."""
        body = {"values": [values]}
        self.svc.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=f"'{tab_name}'!A1",
            body=body, valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS"
        ).execute()

    def _col_letter(self, n: int) -> str:
        """1->A, 2->B, ..., 27->AA, etc."""
        result = ""
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result


# === Workflow Engine ===

class TopolEngine:
    def __init__(self, client: SheetsClient):
        self.client = client

    def scan_step(self, step: Dict) -> List[Dict]:
        """Сканировать таблицу на предмет срабатывания триггера."""
        trigger = step["trigger"]
        source_path = trigger["source_tab"]
        sid, tab = self.client._resolve_tab(source_path)
        rows = self.client.get_all_rows(sid, tab)

        changes = []
        for rd in rows:
            if self._check_trigger(rd, trigger):
                changes.append({"row": rd, "step": step})
        return changes

    def _check_trigger(self, row: Dict, trigger: Dict) -> bool:
        """Проверить условия триггера на строке."""
        status_col = trigger.get("status_col")
        status_val = trigger.get("value")
        fields = trigger.get("fields", [])
        conditions = trigger.get("conditions", "ANY")

        # Проверка status_col
        if status_col:
            actual = str(row.get(status_col, "")).strip()
            expected = str(status_val).strip()
            if status_val == "filled":
                if not actual or actual in ("—", "-", ""):
                    return False
            elif actual != expected:
                return False

        # Проверка fields
        if fields:
            results = []
            for f in fields:
                val = str(row.get(f, "")).strip()
                results.append(bool(val and val not in ("—", "-", "")))
            if conditions == "ALL":
                return all(results)
            else:
                return any(results)

        return True if (status_col or fields) else False

    def execute_step(self, changes: List[Dict]) -> int:
        """Выполнить действия для изменений."""
        count = 0
        for change in changes:
            step = change["step"]
            action = step["action"]
            row = change["row"]

            log.info(f"  Step {step['id']}: {step['name']} — row {row.get('_row')}")

            if action in ("copy_to_client", "send_to_client"):
                self._copy_row_to_target(row, step)
            elif action == "sync_bidirectional":
                self._sync_field(row, step)
            elif action == "assign_to_montager":
                self._assign_montager(row, step)
            elif action == "send_to_scenarist":
                self._send_to_scenarist(row, step)
            elif action == "update_client_table":
                self._update_client(row, step)
            elif action == "notify_manager":
                log.info(f"    [NOTIFY] Менеджеру: строка {row.get('_row')} готова к монтажу")

            count += 1
        return count

    def _copy_row_to_target(self, row: Dict, step: Dict):
        """Копировать строку в целевую таблицу."""
        target_path = step["target"]
        sid, tab = self.client._resolve_tab(target_path)
        headers = self.client.get_headers(sid, tab)
        # Копируем все совпадающие поля
        values = {}
        for h in headers:
            if h in row:
                values[h] = row[h]
        log.info(f"    Copying {len(values)} fields to {tab}")
        # ... implementation depends on exact field mapping

    def _sync_field(self, row: Dict, step: Dict):
        """Синхронизировать поле туда-обратно между таблицами."""
        fields = step["trigger"].get("fields", [])
        target_path = step["target"]
        sid, tab = self.client._resolve_tab(target_path)
        # Find matching row in target by ID
        for f in fields:
            val = row.get(f, "")
            if val:
                target_row, t_row_num = self.client.find_row_by_field(sid, tab, "ID", row.get("ID", ""))
                if target_row:
                    self.client.update_row(sid, tab, t_row_num, {f: val})
                    log.info(f"    Synced {f} -> {tab}")
                break

    def _assign_montager(self, row: Dict, step: Dict):
        """Назначить монтажёру задание."""
        target_path = step["target"]
        sid, tab = self.client._resolve_tab(target_path)
        montager_name = row.get("Выбор монтажера", "")
        if montager_name:
            log.info(f"    Assigning to montager: {montager_name}")
            # Copy relevant fields to montager's sheet
            self.client.append_row(sid, tab, [
                datetime.now().strftime("%d.%m.%Y"),
                row.get("ID", ""),
                row.get("Проект", ""),
                montager_name,
            ])

    def _send_to_scenarist(self, row: Dict, step: Dict):
        """Отправить одобренный монтаж сценаристу."""
        target_path = step["target"]
        sid, tab = self.client._resolve_tab(target_path)
        link = row.get("Ссылка с Готовым материалом", "")
        if link:
            target_row, t_row_num = self.client.find_row_by_field(sid, tab, "ID", row.get("ID", ""))
            if target_row:
                self.client.update_row(sid, tab, t_row_num, {
                    "Ссылка с Готовым материалом": link,
                    "Одобрение клиента": row.get("Одобрение клиента", ""),
                })
                log.info(f"    Sent montage link to scenarist")

    def _update_client(self, row: Dict, step: Dict):
        """Обновить клиентскую таблицу с датой и описанием."""
        target_path = step["target"]
        sid, tab = self.client._resolve_tab(target_path)
        date_field = "Дата Готового монтажа"
        desc_field = "Описание"
        target_row, t_row_num = self.client.find_row_by_field(sid, tab, "ID", row.get("ID", ""))
        if target_row:
            self.client.update_row(sid, tab, t_row_num, {
                date_field: row.get(date_field, ""),
                desc_field: row.get(desc_field, ""),
            })
            log.info(f"    Updated client table with date + description")

    def run_cycle(self):
        """Один полный цикл проверки всех шагов."""
        log.info("=" * 50)
        log.info(f"TOПОЛЬ cycle: {datetime.now().isoformat()}")
        total = 0
        for step in WORKFLOW["steps"]:
            try:
                changes = self.scan_step(step)
                if changes:
                    log.info(f"Step {step['id']}: {step['name']} — {len(changes)} строк(а)")
                    n = self.execute_step(changes)
                    total += n
            except Exception as e:
                log.error(f"Step {step['id']} ERROR: {e}")
        log.info(f"Cycle done: {total} actions")


def main():
    client = SheetsClient()
    engine = TopolEngine(client)

    # Test: print tables metadata
    log.info("=== ТОПОЛЬ started ===")
    for name, cfg in SHEETS.items():
        log.info(f"  {name}: {cfg['description']} ({len(cfg['tabs'])} tabs)")

    # Run once
    engine.run_cycle()


if __name__ == "__main__":
    main()
