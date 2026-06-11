"""
restore_scenariisbor.py — восстановление листа СценарииСбор из клиентских табов.

Инцидент стёр ~676 строк из СценарииСбор. Данные клиентских табов (ВсеСвои,
ВсеСвоиКраснодар, ВсеСвоиПитер и др.) целы. Этот скрипт переносит строки
обратно — но, в отличие от удалённого Step 0, мэппинг идёт ПО ИМЕНИ КОЛОНКИ,
а не по позиции. Колонки, которых нет в целевом листе, просто игнорируются;
ничего не «съезжает».

БЕЗОПАСНОСТЬ:
  * По умолчанию режим REPORT — только показывает, сколько строк добавилось бы.
  * Реальная запись только при --apply И --yes.
  * Дедуп по ID: строки, чей ID уже есть в СценарииСбор, пропускаются.
  * ВАЖНО: запускать при ОСТАНОВЛЕННОМ движке (или с TOPOL_DRY_RUN=1), чтобы
    восстановленные строки с «Выбор монтажёра» не ушли сразу в Step 5.

Запуск в контейнере:
  docker exec topol-engine python3 /app/restore_scenariisbor.py            # отчёт
  docker exec topol-engine python3 /app/restore_scenariisbor.py --apply --yes
"""

import sys, argparse
sys.path.insert(0, "/app")

from engine import SheetsClient, SYSTEM_TABS, api_call
from config import SHEETS

REF_ID = SHEETS["montage_reference"]["id"]
TARGET_TAB = "СценарииСбор"
ID_HEADER = "ID"
APPEND_CHUNK = 100


def list_client_tabs(client: SheetsClient):
    """Все табы Спр_Монтаж минус системные и минус сам целевой лист."""
    meta = client.svc.spreadsheets().get(spreadsheetId=REF_ID, fields="sheets/properties/title").execute()
    titles = [sh["properties"]["title"] for sh in meta.get("sheets", [])]
    return [t for t in titles if t not in SYSTEM_TABS and t != TARGET_TAB]


def existing_ids(client: SheetsClient):
    rows = client.get_recent_rows(REF_ID, TARGET_TAB, limit=5000)
    return {str(r.get(ID_HEADER, "")).strip() for r in rows if str(r.get(ID_HEADER, "")).strip()}


def build_row(src_row: dict, target_headers: dict):
    """Собирает строку-массив в порядке колонок целевого листа, мэппинг по имени."""
    width = (max(target_headers.values()) + 1) if target_headers else 0
    arr = [""] * width
    for name, idx in target_headers.items():
        if name in src_row:
            arr[idx] = str(src_row[name])
    return arr


def append_chunked(client: SheetsClient, rows_arr: list):
    for i in range(0, len(rows_arr), APPEND_CHUNK):
        chunk = rows_arr[i:i + APPEND_CHUNK]
        body = {"values": chunk}
        api_call(lambda: client.svc.spreadsheets().values().append(
            spreadsheetId=REF_ID, range="'" + TARGET_TAB + "'!A1",
            body=body, valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS"
        ).execute())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--tabs", nargs="*", help="ограничить конкретными табами (по умолчанию все клиентские)")
    args = ap.parse_args()
    apply = args.apply and args.yes
    if args.apply and not args.yes:
        print("!! --apply без --yes: остаюсь в режиме отчёта.")

    client = SheetsClient()
    target_headers = client._get_headers(REF_ID, TARGET_TAB)
    have = existing_ids(client)
    print("Целевой лист {}: {} колонок, {} существующих ID".format(TARGET_TAB, len(target_headers), len(have)))

    tabs = args.tabs if args.tabs else list_client_tabs(client)
    print("Клиентских табов к разбору: {}".format(len(tabs)))

    to_append = []
    seen = set(have)
    for tab in tabs:
        try:
            rows = client.get_recent_rows(REF_ID, tab, limit=5000)
        except Exception as e:
            print("  {}: пропуск ({})".format(tab, str(e)[:80]))
            continue
        added = 0
        for rd in rows:
            rid = str(rd.get(ID_HEADER, "")).strip()
            if not rid or rid in seen:
                continue
            seen.add(rid)
            to_append.append(build_row(rd, target_headers))
            added += 1
        print("  {:<24} строк={:>4} новых={:>4}".format(tab, len(rows), added))

    print("\nВсего к восстановлению: {} строк".format(len(to_append)))
    if not apply:
        print("РЕЖИМ ОТЧЁТА. Для записи: --apply --yes")
        if to_append:
            print("Пример первой строки (имя=значение):")
            inv = {v: k for k, v in target_headers.items()}
            for idx, val in enumerate(to_append[0]):
                if val:
                    print("   {} = {!r}".format(inv.get(idx, idx), val[:50]))
        return

    append_chunked(client, to_append)
    print("Записано {} строк в {}.".format(len(to_append), TARGET_TAB))


if __name__ == "__main__":
    main()
