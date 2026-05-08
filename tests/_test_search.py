"""Тесты для search_engine — разные сценарии."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.db")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. Лабораторная (нужны компьютеры)
print("=== Лабораторная работа (нужны компьютеры) ===")
r = c.execute("""
    SELECT s.id FROM schedule s
    JOIN lessons l ON s.lesson_id = l.id
    WHERE l.needs_computers = 1
    LIMIT 1
""").fetchone()
sid = r["id"]
from search_engine import get_lesson_info, get_valid_alternatives
info = get_lesson_info(sid)
alts = get_valid_alternatives(sid)
print(f"Занятие: {info['lesson_title']} ({info['lesson_type']})")
print(f"Группа: {info['group_name']} ({info['students_count']} чел.)")
print(f"Нужно: proj={info['needs_projector']}, comp={info['needs_computers']}")
print(f"Альтернатив: {len(alts)}")
for a in alts[:5]:
    print(f"  {a['name']:15s} cap={a['capacity']} proj={a['has_projector']} comp={a['has_computers']}")

# 2. Лекционная (нужен только проектор)
print("\n=== Лекция (нужен проектор) ===")
r = c.execute("""
    SELECT s.id FROM schedule s
    JOIN lessons l ON s.lesson_id = l.id
    WHERE l.lesson_type = 'Лекционные' AND l.needs_projector = 1
    LIMIT 1
""").fetchone()
sid = r["id"]
info = get_lesson_info(sid)
alts = get_valid_alternatives(sid)
print(f"Занятие: {info['lesson_title']} ({info['lesson_type']})")
print(f"Группа: {info['group_name']} ({info['students_count']} чел.)")
print(f"Альтернатив: {len(alts)}")
for a in alts[:5]:
    print(f"  {a['name']:15s} cap={a['capacity']} proj={a['has_projector']} comp={a['has_computers']}")

# 3. Занятие в Online — должно найти много вариантов
print("\n=== Онлайн-занятие ===")
r = c.execute("""
    SELECT s.id FROM schedule s
    JOIN rooms r ON s.room_id = r.id
    WHERE r.building = 'Онлайн'
    LIMIT 1
""").fetchone()
sid = r["id"]
info = get_lesson_info(sid)
alts = get_valid_alternatives(sid)
print(f"Занятие: {info['lesson_title']}")
print(f"Нужно: proj={info['needs_projector']}, comp={info['needs_computers']}")
print(f"Альтернатив: {len(alts)}")

# 4. Большая группа (потоковая лекция)
print("\n=== Большая группа (>30 чел.) ===")
r = c.execute("""
    SELECT s.id FROM schedule s
    JOIN groups g ON s.group_id = g.id
    WHERE g.students_count > 30
    ORDER BY g.students_count DESC
    LIMIT 1
""").fetchone()
sid = r["id"]
info = get_lesson_info(sid)
alts = get_valid_alternatives(sid)
print(f"Занятие: {info['lesson_title']}")
print(f"Группа: {info['group_name']} ({info['students_count']} чел.)")
print(f"Альтернатив: {len(alts)}")
for a in alts[:5]:
    print(f"  {a['name']:15s} cap={a['capacity']} proj={a['has_projector']} comp={a['has_computers']}")

conn.close()
print("\nВсе тесты прошли успешно!")
