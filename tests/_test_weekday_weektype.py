"""Проверка: учитываются ли weekday и week_type в запросах"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.db")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Покажем сам SQL-запрос из search_engine
print("=== SQL-запрос get_free_rooms ===")
print("""
    SELECT ... FROM rooms r
    WHERE r.id NOT IN (
        SELECT s.room_id FROM schedule s
        WHERE s.weekday = ?          -- день недели
          AND s.week_type = ?        -- верхняя/нижняя
          AND s.start < ?
          AND s.end > ?
    )
""")

# Проверим на практике: аудитория Л-550
print("=== Занятия в аудитории Л-550 ===")
c.execute("""
    SELECT s.weekday, s.week_type, substr(s.start,12,5), substr(s.end,12,5)
    FROM schedule s JOIN rooms r ON s.room_id = r.id
    WHERE r.name = 'Л-550'
    ORDER BY s.weekday, s.start
""")
for r in c.fetchall():
    print(f"  {r[0]:12s} | {r[1]:5s} | {r[2]}-{r[3]}")

# Теперь покажем: поиск свободных для Пн верхняя vs Пн нижняя
from search_engine import get_free_rooms

free_upper = get_free_rooms("Понедельник", "2026-01-12T10:50:00+03:00", "2026-01-12T12:25:00+03:00", "upper")
free_lower = get_free_rooms("Понедельник", "2026-01-12T10:50:00+03:00", "2026-01-12T12:25:00+03:00", "lower")
print(f"\nСвободных Понедельник 10:50-12:25 (верхняя): {len(free_upper)}")
print(f"Свободных Понедельник 10:50-12:25 (нижняя):  {len(free_lower)}")

# Есть ли Л-550 среди свободных?
upper_ids = {r['id'] for r in free_upper}
lower_ids = {r['id'] for r in free_lower}
# Найдём id Л-550
c.execute("SELECT id FROM rooms WHERE name = 'Л-550'")
room_550_id = c.fetchone()['id']
print(f"  Л-550 свободна на верхней? {room_550_id not in upper_ids}")
print(f"  Л-550 свободна на нижней?  {room_550_id not in lower_ids}")

# Разные дни недели
free_mon = get_free_rooms("Понедельник", "2026-01-12T10:50:00+03:00", "2026-01-12T12:25:00+03:00", "upper")
free_fri = get_free_rooms("Пятница", "2026-01-16T10:50:00+03:00", "2026-01-16T12:25:00+03:00", "upper")
print(f"\nСвободных Понедельник 10:50 (upper): {len(free_mon)}")
print(f"Свободных Пятница   10:50 (upper): {len(free_fri)}")
print(f"Разные пулы? {len(free_mon) != len(free_fri)}")

conn.close()
