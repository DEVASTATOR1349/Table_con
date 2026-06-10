"""
Тополь — PostgreSQL writer
Дублирует все изменения из Google Sheets в SQL.
"""

import os
import logging
from datetime import datetime

log = logging.getLogger("topol-db")

DB_CONFIG = {
    "host": os.environ.get("PGHOST", "postgres"),
    "port": int(os.environ.get("PGPORT", 5432)),
    "dbname": os.environ.get("PGDATABASE", "topol"),
    "user": os.environ.get("PGUSER", "topol"),
    "password": os.environ.get("PGPASSWORD", "Topol2026!"),
}


def _conn():
    import psycopg2
    return psycopg2.connect(**DB_CONFIG)


def ensure_tables():
    """Убедиться что таблицы существуют (выполняется один раз при старте)."""
    try:
        c = _conn()
        cur = c.cursor()
        # Core tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id SERIAL PRIMARY KEY,
                sheet_row_id VARCHAR(50), sheet_sid VARCHAR(100), sheet_tab VARCHAR(100),
                project VARCHAR(255), date DATE, link VARCHAR(2000),
                category VARCHAR(255), scenario_type VARCHAR(100),
                scenarist VARCHAR(255), speaker VARCHAR(255),
                transcript TEXT, timeline TEXT, scenario_text TEXT,
                montage_tz TEXT, hook TEXT, retention VARCHAR(50), cta TEXT,
                cover_text VARCHAR(1000), comment TEXT,
                status VARCHAR(50) DEFAULT 'new',
                created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_scenarios_status ON scenarios(status);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS montage_tasks (
                id SERIAL PRIMARY KEY,
                sheet_row_id VARCHAR(50), sheet_sid VARCHAR(100), sheet_tab VARCHAR(100),
                project VARCHAR(255), scenarist VARCHAR(255),
                cover_text VARCHAR(1000), scenario_text TEXT,
                deadline DATE, source_link VARCHAR(2000),
                client_style TEXT, montage_tz TEXT, montage_tz_extra TEXT,
                status_scenarist VARCHAR(50), comment_scenarist TEXT,
                source_approved VARCHAR(50), comment_source TEXT,
                montager VARCHAR(255), price VARCHAR(50),
                ready_link VARCHAR(2000), status_montager VARCHAR(50),
                comment_montager TEXT, approved VARCHAR(50), comment_manager TEXT,
                ready_date DATE, client_approved VARCHAR(50), client_comment TEXT,
                created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_montage_status ON montage_tasks(status_montager);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id SERIAL PRIMARY KEY,
                step_id INT, action VARCHAR(100),
                source_table VARCHAR(255), target_table VARCHAR(255),
                sheet_row INT, details TEXT,
                status VARCHAR(20) DEFAULT 'ok',
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_sync_log_time ON sync_log(created_at);
        """)
        c.commit()
        cur.close()
        c.close()
        log.info("DB tables ready")
    except Exception as e:
        log.warning("DB init skipped: %s", e)


def log_sync(step_id: int, action: str, source: str, target: str, sheet_row: int, details: str = "", status: str = "ok"):
    """Записать событие синхронизации в sync_log."""
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            "INSERT INTO sync_log (step_id, action, source_table, target_table, row_id, details, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (step_id, action, source, target, str(sheet_row), details[:2000] if details else "", status),
        )
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        log.warning("sync_log failed: %s", e)


def upsert_scenario(row: dict, sheet_sid: str, sheet_tab: str):
    """Вставить или обновить сценарий в PostgreSQL."""
    try:
        c = _conn()
        cur = c.cursor()
        row_id = str(row.get("ID", row.get("id", row.get("_row", ""))))
        cur.execute("SELECT id FROM scenarios WHERE sheet_row_id=%s AND sheet_sid=%s", (row_id, sheet_sid))
        existing = cur.fetchone()

        values = (
            row_id, sheet_sid, sheet_tab,
            str(row.get("Проект", "")), str(row.get("Дата", "")),
            str(row.get("Ссылка", "")), str(row.get("Категория", "")),
            str(row.get("Формат", "")), str(row.get("Сценарист", "")),
            str(row.get("Speaker", "")), str(row.get("Transcript", "")),
            str(row.get("Timeline", "")), str(row.get("Сценарий", "")),
            str(row.get("ТЗ монтажа", "")), str(row.get("Хук", "")),
            str(row.get("Retention", "")), str(row.get("CTA", "")),
            str(row.get("Текст на обложке", "")), str(row.get("Комментарий", "")),
            str(row.get("Статус", row.get("status", "new"))),
        )
        if existing:
            cur.execute("""
                UPDATE scenarios SET
                    project=%s, date=%s::date, link=%s, category=%s,
                    scenario_type=%s, scenarist=%s, speaker=%s,
                    transcript=%s, timeline=%s, scenario_text=%s,
                    montage_tz=%s, hook=%s, retention=%s, cta=%s,
                    cover_text=%s, comment=%s, status=%s,
                    updated_at=NOW()
                WHERE id=%s
            """, (*values[3:], existing[0]))
        else:
            cur.execute("""
                INSERT INTO scenarios (sheet_row_id, sheet_sid, sheet_tab,
                    project, date, link, category, scenario_type,
                    scenarist, speaker, transcript, timeline, scenario_text,
                    montage_tz, hook, retention, cta, cover_text, comment, status)
                VALUES (%s,%s,%s,%s,%s::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, values)
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        log.warning("upsert_scenario failed: %s", e)


def upsert_montage(row: dict, sheet_sid: str, sheet_tab: str):
    """Вставить или обновить задание монтажа в PostgreSQL."""
    try:
        c = _conn()
        cur = c.cursor()
        row_id = str(row.get("ID", row.get("id", row.get("_row", ""))))
        cur.execute("SELECT id FROM montage_tasks WHERE sheet_row_id=%s AND sheet_sid=%s", (row_id, sheet_sid))
        existing = cur.fetchone()

        values = (
            row_id, sheet_sid, sheet_tab,
            str(row.get("Проект", "")), str(row.get("Сценарист", "")),
            str(row.get("Текст на обложке", "")), str(row.get("Сценарий", "")),
            str(row.get("Дата дедлайна", "")), str(row.get("Ссылка с исходником и обложкой", "")),
            str(row.get("Фирменный стиль клиента", "")), str(row.get("ТЗ для монтажа", "")),
            str(row.get("ТЗ монтажа доп", "")),
            str(row.get("Статус Сценариста", "")), str(row.get("Комментарий Сценариста", "")),
            str(row.get("Одобрение исходника", "")), str(row.get("Комментарий", "")),
            str(row.get("Выбор монтажера", "")), str(row.get("Цена монтажа", "")),
            str(row.get("Ссылка с Готовым материалом", "")),
            str(row.get("Статус монтажера", "")), str(row.get("Комментарий Монтажёра", row.get("Коммент От  монтажора", ""))),
            str(row.get("Одобрение", "")), str(row.get("Коментарий Ответственного по монтажу", "")),
            str(row.get("Дата Готового монтажа", "")),
            str(row.get("Одобрение клиента", "")), str(row.get("Комент клиента", "")),
        )
        if existing:
            cur.execute("""
                UPDATE montage_tasks SET project=%s, scenarist=%s, cover_text=%s,
                    scenario_text=%s, deadline=%s::date, source_link=%s,
                    client_style=%s, montage_tz=%s, montage_tz_extra=%s,
                    status_scenarist=%s, comment_scenarist=%s,
                    source_approved=%s, comment_source=%s, montager=%s,
                    price=%s, ready_link=%s, status_montager=%s,
                    comment_montager=%s, approved=%s, comment_manager=%s,
                    ready_date=%s::date, client_approved=%s, client_comment=%s,
                    updated_at=NOW()
                WHERE id=%s
            """, (*values[3:], existing[0]))
        else:
            cur.execute("""
                INSERT INTO montage_tasks (sheet_row_id, sheet_sid, sheet_tab,
                    project, scenarist, cover_text, scenario_text,
                    deadline, source_link, client_style, montage_tz, montage_tz_extra,
                    status_scenarist, comment_scenarist, source_approved, comment_source,
                    montager, price, ready_link, status_montager, comment_montager,
                    approved, comment_manager, ready_date, client_approved, client_comment)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date,%s,%s)
            """, values)
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        log.warning("upsert_montage failed: %s", e)
