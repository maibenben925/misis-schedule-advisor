"""Миграция: добавляем колонку booking_date (DATE) в transfers и event_bookings."""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..\\data\\schedule.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Проверяем, нужна ли миграция
cur.execute("PRAGMA table_info(transfers)")
cols = [r[1] for r in cur.fetchall()]
if "booking_date" not in cols:
    cur.execute("ALTER TABLE transfers ADD COLUMN booking_date TEXT")
    print("Added booking_date to transfers")

cur.execute("PRAGMA table_info(event_bookings)")
cols = [r[1] for r in cur.fetchall()]
if "booking_date" not in cols:
    cur.execute("ALTER TABLE event_bookings ADD COLUMN booking_date TEXT")
    print("Added booking_date to event_bookings")

conn.commit()

# Заполняем booking_date для существующих записей на основе weekday+week_type
# Используем BASE_MONDAY = 2026-01-12
from datetime import date, timedelta

BASE_MONDAY = date(2026, 1, 12)
WD_MAP = {"Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3, "Пятница": 4, "Суббота": 5}

# Переносы
cur.execute("SELECT id, weekday, week_type FROM transfers WHERE booking_date IS NULL")
rows = cur.fetchall()
for tid, wd, wt in rows:
    wd_idx = WD_MAP.get(wd, 0)
    # Находим ближайшую дату с этим weekday и week_type от BASE_MONDAY
    base_dow = BASE_MONDAY.weekday()  # 0 = Monday
    days_ahead = (wd_idx - base_dow) % 7
    target = BASE_MONDAY + timedelta(days=days_ahead)
    # Корректируем на week_type
    week_num = (target - BASE_MONDAY).days // 7
    if wt == "upper" and week_num % 2 != 0:
        target += timedelta(days=7)
    elif wt == "lower" and week_num % 2 == 0:
        target += timedelta(days=7)
    cur.execute("UPDATE transfers SET booking_date=? WHERE id=?", (str(target), tid))
    print(f"  Transfer #{tid}: {wd} {wt} -> {target}")

# Бронирования
cur.execute("SELECT id, weekday, week_type FROM event_bookings WHERE booking_date IS NULL")
rows = cur.fetchall()
for bid, wd, wt in rows:
    wd_idx = WD_MAP.get(wd, 0)
    base_dow = BASE_MONDAY.weekday()
    days_ahead = (wd_idx - base_dow) % 7
    target = BASE_MONDAY + timedelta(days=days_ahead)
    week_num = (target - BASE_MONDAY).days // 7
    if wt == "upper" and week_num % 2 != 0:
        target += timedelta(days=7)
    elif wt == "lower" and week_num % 2 == 0:
        target += timedelta(days=7)
    cur.execute("UPDATE event_bookings SET booking_date=? WHERE id=?", (str(target), bid))
    print(f"  Booking #{bid}: {wd} {wt} -> {target}")

conn.commit()
conn.close()
print("Migration complete!")
