import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import get_rooms_list, get_buildings, to_iso

print("Rooms:", len(get_rooms_list()))
print("Buildings:", get_buildings())
print("to_iso:", to_iso("10:50"))

import sqlite3
conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.db"))
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("\n--- Топ-5 по вместимости ---")
c.execute("SELECT name, capacity FROM rooms ORDER BY capacity DESC LIMIT 5")
for r in c.fetchall():
    print(f"  {r['name']:20s} cap={r['capacity']}")

print("\n--- Лекционные (cap > 80) ---")
c.execute("SELECT name, capacity FROM rooms WHERE capacity > 80 ORDER BY capacity DESC")
for r in c.fetchall():
    print(f"  {r['name']:20s} cap={r['capacity']}")

print("\n--- Обычные (cap <= 50) ---")
c.execute("SELECT name, capacity FROM rooms WHERE capacity <= 50 ORDER BY capacity DESC LIMIT 10")
for r in c.fetchall():
    print(f"  {r['name']:20s} cap={r['capacity']}")

conn.close()
print("\nOK")
