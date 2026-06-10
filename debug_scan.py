import sys, json
sys.path.insert(0, '/app')
from engine import SheetsClient
c = SheetsClient()

sid = '1zVNwBX7e8FIZ-0bP7qU2UTbueXrukoev0NbSCS9EwHQ'
print("=== NOMOS tab ===")
h = c._get_headers(sid, 'Номос')
if isinstance(h, dict):
    print("Headers:", len(h), "|", list(h.keys())[:5])
else:
    print("Headers:", len(h), "|", h[0:5])
rows = c.get_recent_rows(sid, 'Номос')
print("Rows:", len(rows))
if rows:
    r0 = rows[0]
    print("First row _row:", r0.get('_row'))
    print("Last row _row:", rows[-1].get('_row'))
else:
    print("ZERO ROWS!")

sid2 = '1paHyEIxdB2tojNPRfTF58DFirMOYROcwtJNQeM3J5y4'
print()
print("=== SPR Montage tab ===")
h2 = c._get_headers(sid2, 'СценарииСбор')
if isinstance(h2, dict):
    print("Headers:", len(h2), "|", list(h2.keys())[:10])
else:
    print("Headers:", len(h2), "|", h2[0:10])
rows2 = c.get_recent_rows(sid2, 'СценарииСбор')
print("Rows:", len(rows2))
if rows2:
    r0 = rows2[0]
    print("First row _row:", r0.get('_row'))
    print("Last row _row:", rows2[-1].get('_row'))
    print()
    print("=== Trigger columns on last 5 rows ===")
    for row in rows2[-5:]:
        rn = row.get('_row', '?')
        sc = str(row.get('Статус Сценариста', '—'))[:40]
        od = str(row.get('Одобрение исходника', '—'))[:40]
        mt = str(row.get('Выбор монтажера', '—'))[:40]
        dl = str(row.get('Дата дедлайна', '—'))[:40]
        sr = str(row.get('Ссылка с исходником', '—'))[:40]
        odobr = str(row.get('Одобрение', '—'))[:40]
        proj = str(row.get('Проект', '—'))[:40]
        print("  Row {}: Проект={} | Дедлайн={} | Исходник={} | СтатСцен={} | ОдобрИсх={} | Монтаж={} | Одобр={}".format(rn, proj, dl, sr, sc, od, mt, odobr))
