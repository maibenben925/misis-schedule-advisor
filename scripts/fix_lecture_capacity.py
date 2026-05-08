"""
Исправление вместимости лекционных аудиторий.

Аудитории, где проходят лекции → cap=100-150.
Аудитории, где ТОЛЬКО практика/лабы → cap остаётся как есть (20-50).
"""
import sqlite3
import os
import random

random.seed(42)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..\\data\\schedule.db")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Находим аудитории, где идут лекции
c.execute("""
    SELECT r.id, r.name, r.building, r.floor, r.capacity,
           COUNT(DISTINCT s.id) as lecture_sessions
    FROM schedule s
    JOIN rooms r ON s.room_id = r.id
    JOIN lessons l ON s.lesson_id = l.id
    WHERE l.lesson_type = 'Лекционные'
    GROUP BY r.id
""")
lecture_rooms = {r[0]: r for r in c.fetchall()}

print(f"Аудиторий с лекциями: {len(lecture_rooms)}")

updates = []
for room_id, name, building, floor, old_cap, sessions in lecture_rooms.values():
    if building == "Онлайн":
        continue

    # Лекционная аудитория: много места + проектор
    if sessions >= 50:
        # Очень большая лекционная (Б-4, Б-934, Л-556 и т.д.)
        new_cap = random.randint(130, 180)
    elif sessions >= 10:
        # Большая лекционная
        new_cap = random.randint(100, 150)
    else:
        # Умеренная лекционная
        new_cap = random.randint(80, 120)

    updates.append((new_cap, True, False, room_id))
    print(f"  {name:15s} | cap {old_cap:3d} → {new_cap:3d} | лекций={sessions}")

c.executemany(
    "UPDATE rooms SET capacity = ?, has_projector = ?, has_computers = ? WHERE id = ?",
    updates,
)
conn.commit()

# Проверка
print("\n--- Проверка ---")
c.execute("""
    SELECT r.name, r.capacity,
           SUM(CASE WHEN l.lesson_type = 'Лекционные' THEN 1 ELSE 0 END) as lectures
    FROM rooms r
    LEFT JOIN schedule s ON s.room_id = r.id
    LEFT JOIN lessons l ON s.lesson_id = l.id
    WHERE r.building != 'Онлайн'
    GROUP BY r.id
    ORDER BY r.building, r.name
    LIMIT 20
""")
for r in c.fetchall():
    print(f"  {r[0]:15s} | cap={r[1]:3d} | lectures={r[2]}")

conn.close()
print("\nГотово!")
