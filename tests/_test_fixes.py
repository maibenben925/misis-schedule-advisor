"""Проверка всех фиксов"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import (
    get_conn, get_affected_lessons, get_affected_lessons_period,
    get_transfers_for_slot, get_bookings_for_slot, to_iso,
    get_schedule_grid
)

# 1. Проверка get_transfers_for_slot — должен иметь new_room_id
tr = get_transfers_for_slot("Понедельник", "09:00", "10:35", "upper")
print(f"Transfers for slot: {len(tr)}")
if tr:
    print(f"  Ключи: {tr[0].keys()}")
    print(f"  new_room_id доступен: {tr[0]['new_room_id']}")

# 2. Проверка get_bookings_for_slot — должен иметь room_id
bk = get_bookings_for_slot("Понедельник", "09:00", "10:35", "upper")
print(f"Bookings for slot: {len(bk)}")
if bk:
    print(f"  Ключи: {bk[0].keys()}")
    print(f"  room_id доступен: {bk[0]['room_id']}")

# 3. Проверка affected lessons для Г-311 в Среду
conn = get_conn()
c = conn.cursor()
c.execute("SELECT id FROM rooms WHERE name = 'Г-311'")
row = c.fetchone()
if row:
    room_id = row[0]
    print(f"\nГ-311 id = {room_id}")

    # Проверяем какие занятия есть в Г-311 в Среду
    c.execute("""
        SELECT s.id, r.name, s.weekday, s.start, s.end, s.week_type, l.title
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE r.id = ? AND s.weekday = 'Среда'
        ORDER BY s.start
    """, (room_id,))
    for r in c.fetchall():
        print(f"  #{r[0]} {r[6]:40s} | {r[2]:12s} | {r[3][11:16]}-{r[4][11:16]} | {r[5]}")

# 4. Проверка get_affected_lessons — ищем по weekday+week_type (без времени)
conn = get_conn()
c = conn.cursor()
# Получаем id Г-311
c.execute("SELECT id FROM rooms WHERE name = 'Г-311'")
row = c.fetchone()
if row:
    gid = row[0]
    affected = get_affected_lessons([gid], [("Среда", "upper")])
    print(f"\nAffected lessons for Г-311, Среда upper: {len(affected)}")
    for a in affected:
        print(f"  #{a['id']} {a['lesson_title']:40s} | {a['start'][11:16]}-{a['end'][11:16]}")

# 5. Проверка get_affected_lessons_period — с конкретными парами
affected2 = get_affected_lessons_period([gid], "Среда", "upper", ["4-я пара", "5-я пара"])
print(f"\nAffected lessons for Г-311, Среда upper, 4-5 пара: {len(affected2)}")
for a in affected2:
    print(f"  #{a['id']} {a['lesson_title']:40s} | {a['start'][11:16]}-{a['end'][11:16]}")

conn.close()
print("\nALL OK")
