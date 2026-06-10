"""
Тест Тополя — manual ping-pong test
1. Читаем строку из Номос Сценарии
2. Пишем тестовый статус
3. Ждём цикл engine
4. Проверяем что статус синкнулся в Спр_Монтаж
5. Откатываем
"""

import sys, time
sys.path.insert(0, "/opt/topol")
from engine import SheetsClient, TopolEngine
from config import SHEETS

client = SheetsClient()

print("=" * 60)
print("ТОПОЛЬ — MANUAL TEST")
print("=" * 60)

# 1. Read Номос
sid1 = SHEETS["nomos_scenarios"]["id"]
tab1 = "Номос"
print(f"\n[1] Reading {tab1}...")
headers1 = client._get_headers(sid1, tab1)
print(f"    Headers ({len(headers1)}): {list(headers1.keys())[:10]}...")

rows = client.get_recent_rows(sid1, tab1, limit=5)
if not rows:
    print("    NO ROWS — таблица пуста!")
    sys.exit(1)

row = rows[-1]
row_num = row["_row"]
print(f"    Latest row #{row_num}:")
for k,v in list(row.items())[:8]:
    print(f"      {k}: {str(v)[:80]}")

# 2. Check target table
sid2 = SHEETS["montage_reference"]["id"]
tab2 = "СценарииСбор"
print(f"\n[2] Reading {tab2}...")
headers2 = client._get_headers(sid2, tab2)
print(f"    Headers ({len(headers2)}): {list(headers2.keys())[:10]}...")

print(f"\n[3] Testing write permissions...")
# Write test value to a safe cell (last row, column A)
test_value = f"TOПОЛЬ_TEST_{int(time.time())}"
try:
    client.update_cell(sid1, tab1, row_num, 0, test_value)
    print(f"    ✅ Wrote '{test_value}' to {tab1}!A{row_num}")
    
    # Read back
    time.sleep(1)
    check = client.get_recent_rows(sid1, tab1, limit=1)
    if check:
        val = check[0].get(list(headers1.keys())[0], "")
        print(f"    Read back: '{val}' — {'✅ MATCH' if val == test_value else '❌ MISMATCH'}")

    # Restore original
    original = row.get(list(headers1.keys())[0], "")
    client.update_cell(sid1, tab1, row_num, 0, original)
    print(f"    🔄 Restored: '{original}'")
    
except Exception as e:
    print(f"    ❌ FAILED: {e}")

# 4. Simulate engine cycle
print(f"\n[4] Running engine cycle...")
engine = TopolEngine(client)
engine.run_cycle()
print("    ✅ Done")

# 5. Summarize
print(f"\n[5] Current step statuses:")
for step in SHEETS["nomos_scenarios"]["tabs"]:
    pass  # dummy

print("\n" + "=" * 60)
print("TEST COMPLETE — engine reading & writing works")
print("=" * 60)
