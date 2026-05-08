"""Проверка: какие аудитории используются для лекций"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.db")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== Аудитории, где проходят Лекционные ===")
c.execute("""
    SELECT r.id, r.name, r.building, r.floor, r.capacity,
           COUNT(*) as lecture_count
    FROM schedule s
    JOIN rooms r ON s.room_id = r.id
    JOIN lessons l ON s.lesson_id = l.id
    WHERE l.lesson_type = 'Лекционные'
    GROUP BY r.id
    ORDER BY r.building, r.name
""")
for r in c.fetchall():
    print(f"  {r['name']:15s} | {r['building']:10s} | эт.{r['floor']} | cap={r['capacity']:3d} | лекций={r['lecture_count']}")

print("\n=== Группы с большим кол-вом студентов (потоки) ===")
c.execute("""
    SELECT g.id, g.name, g.students_count,
           COUNT(DISTINCT s.lesson_id) as lessons
    FROM schedule s
    JOIN groups g ON s.group_id = g.id
    JOIN lessons l ON s.lesson_id = l.id
    WHERE l.lesson_type = 'Лекционные'
    GROUP BY g.id
    ORDER BY g.students_count DESC
    LIMIT 20
""")
for r in c.fetchall():
    print(f"  {r['name']:20s} | students={r['students_count']} | лекций={r['lessons']}")

conn.close()
