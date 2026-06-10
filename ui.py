"""
Тополь Web UI v2 — лёгкий дашборд (не дёргает API без кнопки)
"""

import json, time, os
from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from jinja2 import Template

app = FastAPI(title="Тополь — Dashboard")

STATE_FILE = "/app/logs/state.json"

def get_cached_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except:
            pass
    return None


HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Тополь — Цепочка движения</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
        h1 { color: #58a6ff; font-size: 22px; }
        .subtitle { color: #8b949e; font-size: 13px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; margin-bottom: 24px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
        .card h3 { font-size: 14px; color: #58a6ff; margin-bottom: 4px; }
        .card .id { color: #8b949e; font-size: 11px; margin-bottom: 8px; }
        .row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #21262d; font-size: 13px; }
        .row:last-child { border-bottom: none; }
        .row .label { color: #8b949e; }
        .row .value { color: #c9d1d9; text-align: right; }
        .steps { display: flex; flex-direction: column; gap: 8px; }
        .step { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; }
        .step-num { width: 30px; height: 30px; border-radius: 50%; background: #21262d; color: #58a6ff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; flex-shrink: 0; }
        .step-num.on { background: #1a3a2a; color: #3fb950; }
        .step-info { flex: 1; }
        .step-info .name { font-size: 13px; font-weight: 600; }
        .step-info .meta { font-size: 10px; color: #8b949e; margin-top: 1px; }
        .count { font-size: 12px; color: #3fb950; background: #1a3a2a; padding: 2px 8px; border-radius: 12px; white-space: nowrap; }
        .count.zero { color: #8b949e; background: #21262d; }
        button { padding: 6px 14px; background: #21262d; color: #c9d1d9; border: 1px solid #30363d; border-radius: 6px; cursor: pointer; font-size: 13px; }
        button:hover { background: #30363d; }
        button.refresh { background: #1f3a5f; border-color: #1f6feb; color: #58a6ff; }
        button.refresh:hover { background: #234a7a; }
        .age { font-size: 11px; color: #8b949e; }
        .error { background: #3d1e1e; border: 1px solid #8b2e2e; color: #f85149; padding: 10px; border-radius: 6px; font-size: 12px; margin: 10px 0; }
        .empty { color: #484f58; text-align: center; padding: 40px; font-size: 14px; }
        h2 { font-size: 16px; color: #8b949e; margin: 20px 0 10px; }
        pre { background: #0d1117; padding: 10px; border-radius: 4px; font-size: 11px; max-height: 300px; overflow: auto; }
        .log-line { font-family: monospace; font-size: 11px; padding: 2px 0; color: #8b949e; }
    </style>
</head>
<body>
    <h1>🌲 Тополь — Цепочка движения</h1>
    <p class="subtitle">4 таблицы Google Sheets → 9 шагов → видеоконтент клиентам</p>

    <div style="margin-bottom: 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <button class="refresh" onclick="location.href='?refresh=1'">🔄 Обновить (из API)</button>
        <button onclick="location.reload()">📋 Перезагрузить</button>
    </div>

    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}

    <h2>📊 Таблицы (кеш)</h2>
    <div class="grid">
        {% for tbl in tables %}
        <div class="card">
            <h3>{{ tbl.label }}</h3>
            <div class="id">{{ tbl.tab }}</div>
            {% if tbl.error %}
            <div class="error" style="margin-top:6px">{{ tbl.error }}</div>
            {% else %}
            <div class="row"><span class="label">Колонок</span><span class="value">{{ tbl.cols }}</span></div>
            <div class="row"><span class="label">Последняя строка</span><span class="value">#{{ tbl.last_row }}</span></div>
            <div class="row"><span class="label">Строк всего</span><span class="value">{{ tbl.total_rows }}</span></div>
            <div class="row"><span class="label">Просканировано</span><span class="value">{{ tbl.scanned }}</span></div>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <h2>⚡ 9 шагов (состояние)</h2>
    <div class="steps">
        {% for s in steps %}
        <div class="step">
            <div class="step-num {% if s.count and s.count > 0 %}on{% endif %}">{{ s.id }}</div>
            <div class="step-info">
                <div class="name">{{ s.name }}</div>
                <div class="meta">{{ s.source }} → {{ s.target }}</div>
            </div>
            <div class="count {% if not s.count or s.count == 0 %}zero{% endif %}">{{ s.count if s.count else 0 }} стр</div>
        </div>
        {% endfor %}
    </div>

    {% if state_timestamp %}
    <div class="age" style="margin-top: 16px;">Данные от: {{ state_timestamp }} (обновляются каждые 5 мин)</div>
    {% endif %}

    <h2>📝 Последние логи движка</h2>
    <div class="card" style="max-height: 250px; overflow: auto;">
        {% for line in logs %}
        <div class="log-line">{{ line }}</div>
        {% endfor %}
    </div>

    <h2>🔍 Прямой запрос к таблице</h2>
    <form method="get" style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 10px 0;">
        <input name="sheet_id" value="{{ sheet_id or '' }}" placeholder="Sheet ID" style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:6px 10px;border-radius:4px;font-size:12px;flex:1;min-width:200px;">
        <input name="tab_name" value="{{ tab_name or '' }}" placeholder="Вкладка" style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:6px 10px;border-radius:4px;font-size:12px;width:140px;">
        <input name="limit" value="{{ limit }}" style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:6px 10px;border-radius:4px;font-size:12px;width:60px;" placeholder="N">
        <button class="refresh" type="submit">Показать</button>
    </form>
    {% if preview_text %}
    <pre>{{ preview_text }}</pre>
    {% endif %}
</body>
</html>"""


# === State saver (called by engine after each cycle) ===

@app.post("/api/state/save")
async def save_state(body: dict):
    body["ts"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    json.dump(body, open(STATE_FILE, "w"), indent=2, ensure_ascii=False)
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.3.0"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    refresh: str = Query(None),
    sheet_id: str = Query(None),
    tab_name: str = Query(None),
    limit: int = Query(3),
):
    error = None
    tables = []
    steps = []
    ts = None
    logs_lines = []
    preview_text = None

    # Read cached state
    state = get_cached_state()
    if state:
        ts = state.get("ts", "")
        tables = state.get("tables", [])
        steps = state.get("steps", [])
        logs_lines = state.get("logs", [])

    # If user asked for refresh, do a live scan (one table only to save quota)
    if refresh == "1":
        try:
            from engine import SheetsClient
            from config import SHEETS
            client = SheetsClient("/app/service_account.json")
            live_tables = []
            live_steps = []

            # Just scan 2 main tables (enough for dashboard)
            scan_map = [
                ("nomos_scenarios", "Номос", "Номос Сценарии"),
                ("montage_reference", "СценарииСбор", "Спр_Монтаж"),
            ]
            for tk, tn, label in scan_map:
                try:
                    sid = SHEETS[tk]["id"]
                    h = client._get_headers(sid, tn)
                    rows = client.get_recent_rows(sid, tn)
                    live_tables.append({
                        "label": label, "tab": tn, "cols": len(h),
                        "last_row": rows[-1]["_row"] if rows else "—",
                        "total_rows": "?",
                        "scanned": len(rows),
                    })
                except Exception as e:
                    live_tables.append({"label": label, "tab": tn, "cols": "?", "last_row": "?", "total_rows": "?", "scanned": "?", "error": str(e)[:100]})

            # Scan steps (fast, uses cached headers)
            from engine import TopolEngine
            engine = TopolEngine(client)
            for step in [{"id": 1, "name": "Сценарий → клиент", "trigger": {"source_tab": "nomos_scenarios/main"}, "target": "montage_reference/clients"}]:
                try:
                    changes = engine.scan_step(step)
                    live_steps.append({"id": step["id"], "name": step["name"], "source": step["trigger"]["source_tab"], "target": step.get("target", "—"), "count": len(changes)})
                except:
                    live_steps.append({"id": step["id"], "name": step["name"], "source": "?", "target": "?", "count": 0})

            if live_tables:
                tables = live_tables
            if live_steps:
                steps = live_steps
            ts = datetime.now().strftime("%H:%M:%S")
            error = "⚠️ Live refresh: только 2 таблицы (экономия квоты API)"
        except Exception as e:
            error = "Live refresh failed: " + str(e)[:200]

    # Preview specific sheet
    if sheet_id and tab_name:
        try:
            from engine import SheetsClient
            client = SheetsClient("/app/service_account.json")
            h = client._get_headers(sheet_id, tab_name)
            rows = client.get_recent_rows(sheet_id, tab_name, limit=limit)
            lines = [f"=== {tab_name} ({len(h)} колонок) ==="]
            lines.append("  Headers: " + ", ".join(list(h.keys())[:25]))
            for rd in rows[:limit]:
                lines.append(f"--- Row #{rd['_row']} ---")
                for k, v in list(rd.items())[:12]:
                    if k != "_row":
                        lines.append(f"  {k}: {str(v)[:120]}")
            preview_text = "\n".join(lines)
        except Exception as e:
            preview_text = f"ERROR: {e}"

    return HTMLResponse(Template(HTML).render(
        tables=tables, steps=steps, state_timestamp=ts, error=error,
        logs=logs_lines[-20:] if logs_lines else [],
        sheet_id=sheet_id or "", tab_name=tab_name or "", limit=limit,
        preview_text=preview_text,
    ))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=18889)
