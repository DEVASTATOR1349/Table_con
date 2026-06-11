"""
cleanup_montagers.py — удаление ошибочных назначений из таблиц монтажёров.

Контекст инцидента: удалённый ныне Step 0 залил 1142 строки в СценарииСбор
без мэппинга колонок; у многих был заполнен «Выбор монтажёра», и Step 5
разослал ~6038 назначений в таблицы монтажёров — многие не тем людям.

Источник правды о ЛЕГИТИМНЫХ заданиях — PostgreSQL montage_tasks (793 строки,
не пострадал). Строка в ЗаданияV2 монтажёра считается легитимной, если её ID
есть в montage_tasks с этим же монтажёром. Всё остальное — кандидат на удаление.

БЕЗОПАСНОСТЬ:
  * По умолчанию режим REPORT — ничего не удаляет, только печатает и пишет
    отчёт cleanup_report.json.
  * Реальное удаление только при флаге --apply И --yes.
  * Дополнительный потолок --max-delete (по умолчанию строго).

Запуск в контейнере:
  docker exec topol-engine python3 /app/cleanup_montagers.py            # отчёт
  docker exec topol-engine python3 /app/cleanup_montagers.py --apply --yes
"""

import sys, json, argparse
sys.path.insert(0, "/app")

from engine import SheetsClient, MONTAGER_TAB
from config import MONTAGER_SHEETS, MONTAGER_ALIASES
import db

REPORT_FILE = "/app/cleanup_report.json"


def _norm_name(s: str) -> str:
    return str(s or "").replace(" ", "").strip()


def legit_ids_by_montager():
    """Из PG montage_tasks: {normalized_montager_key: set(ID)}.

    montager в PG — это сырое значение «Выбор монтажера»; приводим к ключу
    MONTAGER_SHEETS теми же правилами, что и движок (без пробелов + алиасы).
    """
    out = {}
    try:
        rows = db.fetch("SELECT sheet_row_id, montager FROM montage_tasks WHERE montager IS NOT NULL AND montager <> ''")
    except Exception as e:
        print("!! PG недоступен ({}). Без источника правды удаление невозможно — только отчёт по ID-порогу.".format(e))
        return None
    for row_id, montager in rows:
        key = _norm_name(montager)
        key = MONTAGER_ALIASES.get(key, key)
        out.setdefault(key, set()).add(str(row_id).strip())
    return out


def get_tab_gid(client: SheetsClient, sheet_id: str, tab_name: str):
    meta = client.svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets/properties").execute()
    for sh in meta.get("sheets", []):
        p = sh.get("properties", {})
        if p.get("title") == tab_name:
            return p.get("sheetId")
    return None


def delete_rows(client: SheetsClient, sheet_id: str, gid: int, row_numbers: list):
    """Удаляет строки (1-based номера) пачкой, снизу вверх для устойчивости индексов."""
    reqs = []
    for rn in sorted(row_numbers, reverse=True):
        # deleteDimension использует 0-based полуинтервал [start, end)
        reqs.append({"deleteDimension": {"range": {
            "sheetId": gid, "dimension": "ROWS",
            "startIndex": rn - 1, "endIndex": rn,
        }}})
    if not reqs:
        return
    client.svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id, body={"requests": reqs}
    ).execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="реально удалять (иначе только отчёт)")
    ap.add_argument("--yes", action="store_true", help="подтверждение удаления (нужно вместе с --apply)")
    ap.add_argument("--max-delete", type=int, default=200,
                    help="макс. удалений на одного монтажёра (предохранитель)")
    ap.add_argument("--id-threshold", type=int, default=0,
                    help="если PG недоступен: считать ID > порога мусором (0 = выкл)")
    args = ap.parse_args()

    apply = args.apply and args.yes
    if args.apply and not args.yes:
        print("!! --apply без --yes: остаюсь в режиме отчёта.")

    client = SheetsClient()
    legit = legit_ids_by_montager()
    if legit is None and args.id_threshold <= 0:
        print("!! Нет источника правды и не задан --id-threshold. Только листинг, без флага удаления.")

    report = {"mode": "apply" if apply else "report", "montagers": []}
    grand_del = 0

    for mkey, minfo in MONTAGER_SHEETS.items():
        if not minfo.get("access", False):
            continue
        sid = minfo["id"]
        try:
            rows = client.get_recent_rows(sid, MONTAGER_TAB, limit=5000)
        except Exception as e:
            print("  {}: не прочитать ({})".format(mkey, str(e)[:80]))
            continue

        legit_set = (legit or {}).get(mkey, set())
        to_delete = []
        for rd in rows:
            rid = str(rd.get("ID", "")).strip()
            if not rid:
                continue
            bogus = False
            if legit is not None:
                bogus = rid not in legit_set
            elif args.id_threshold > 0 and rid.isdigit():
                bogus = int(rid) > args.id_threshold
            if bogus:
                to_delete.append({
                    "row": rd.get("_row"), "id": rid,
                    "project": str(rd.get("Проект", ""))[:40],
                })

        # Предохранитель: подозрительно много — не трогаем, требуем ручного разбора
        capped = False
        if len(to_delete) > args.max_delete:
            capped = True

        report["montagers"].append({
            "montager": mkey, "total_rows": len(rows),
            "legit": len(legit_set), "to_delete": len(to_delete),
            "capped": capped, "rows": to_delete[:50],
        })
        print("  {:<24} строк={:>4} легит={:>4} к_удалению={:>4}{}".format(
            mkey, len(rows), len(legit_set), len(to_delete), "  [CAP!]" if capped else ""))

        if apply and to_delete and not capped:
            gid = get_tab_gid(client, sid, MONTAGER_TAB)
            if gid is None:
                print("    !! gid таба {} не найден, пропуск".format(MONTAGER_TAB))
                continue
            delete_rows(client, sid, gid, [d["row"] for d in to_delete])
            grand_del += len(to_delete)
            print("    -> удалено {} строк".format(len(to_delete)))

    json.dump(report, open(REPORT_FILE, "w"), ensure_ascii=False, indent=2)
    print("\nОтчёт: {}".format(REPORT_FILE))
    if apply:
        print("ИТОГО удалено строк: {}".format(grand_del))
    else:
        total = sum(m["to_delete"] for m in report["montagers"])
        print("РЕЖИМ ОТЧЁТА. Кандидатов на удаление: {}. Для удаления: --apply --yes".format(total))


if __name__ == "__main__":
    main()
