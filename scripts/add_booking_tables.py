"""
Добавляет таблицы для хранения переносов и бронирований мероприятий.

Таблицы:
- transfers: история всех замен аудиторий
- event_bookings: бронирование аудиторий под мероприятия
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..\\data\\schedule.db")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# ── Таблица: Переносы (transfers) ──
c.execute("""
CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    schedule_id INTEGER NOT NULL,
    old_room_id INTEGER NOT NULL,
    new_room_id INTEGER NOT NULL,
    weekday TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    week_type TEXT NOT NULL,
    lesson_id INTEGER,
    group_id INTEGER,
    reason TEXT DEFAULT 'Инцидент'
)
""")
print("Создана таблица: transfers")

# ── Талица: Бронирования мероприятий (event_bookings) ──
c.execute("""
CREATE TABLE IF NOT EXISTS event_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    room_id INTEGER NOT NULL,
    weekday TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    week_type TEXT,
    event_name TEXT NOT NULL,
    organizer TEXT,
    attendees_count INTEGER,
    needs_projector BOOLEAN DEFAULT 0,
    needs_computers BOOLEAN DEFAULT 0
)
""")
print("Создана таблица: event_bookings")

conn.commit()

# Проверка
c.execute("PRAGMA table_info(transfers)")
print("\ntransfers columns:")
for col in c.fetchall():
    print(f"  {col[1]} ({col[2]})")

c.execute("PRAGMA table_info(event_bookings)")
print("\nevent_bookings columns:")
for col in c.fetchall():
    print(f"  {col[1]} ({col[2]})")

conn.close()
print("\nГотово!")
