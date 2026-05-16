"""
Модуль расчёта статистики аудиторного фонда.

Метрики, которые помогают принимать решения:
- общая сводка по фонду (с переносами, бронированиями, отменами)
- наиболее / наименее загруженные аудитории
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

EXCLUDED_BUILDINGS = ("Онлайн", "Каф. ИЯКТ", "Спортивный комплекс Беляево")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fund_summary_with_transfers() -> dict:
    """Общая сводка по аудиторному фонду (с переносами, бронированиями, отменами)."""
    conn = _connect()

    n_rooms = conn.execute("""
        SELECT COUNT(*) as cnt FROM rooms WHERE building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    n_buildings = conn.execute("""
        SELECT COUNT(DISTINCT building) as cnt FROM rooms WHERE building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    n_lessons = conn.execute("""
        SELECT COUNT(DISTINCT s.room_id || s.weekday || s.start || s.week_type) as cnt
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    n_groups = conn.execute("""
        SELECT COUNT(DISTINCT s.group_id) as cnt FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    total_capacity = conn.execute("""
        SELECT SUM(capacity) as cnt FROM rooms WHERE building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    avg_capacity = round(total_capacity / n_rooms) if n_rooms else 0

    total_slots = n_rooms * 84

    total_bookings = conn.execute("SELECT COUNT(*) as cnt FROM event_bookings").fetchone()["cnt"]
    total_transfers = conn.execute("SELECT COUNT(*) as cnt FROM transfers").fetchone()["cnt"]

    try:
        total_cancellations = conn.execute("SELECT COUNT(*) as cnt FROM cancellations WHERE is_restored = 0").fetchone()["cnt"]
    except sqlite3.OperationalError:
        total_cancellations = 0

    conn.close()

    load_pct = round(n_lessons / total_slots * 100, 1) if total_slots else 0

    return {
        "rooms": n_rooms,
        "buildings": n_buildings,
        "groups": n_groups,
        "avg_capacity": avg_capacity,
        "total_slots": total_slots,
        "occupied_slots": n_lessons,
        "load_pct": load_pct,
        "transfers": total_transfers,
        "bookings": total_bookings,
        "cancellations": total_cancellations,
    }


def room_load_stats(n: int = 10) -> dict:
    """Наиболее и наименее загруженные аудитории.

    Загрузка = занятые слоты / 84 возможных (6 дней × 7 пар × 2 недели).
    """
    conn = _connect()
    SLOTS_PER_ROOM = 84

    rows = conn.execute("""
        SELECT r.id, r.name, r.building, r.capacity, r.has_computers,
               COUNT(DISTINCT s.weekday || s.start || s.week_type) as occupied_slots
        FROM rooms r
        LEFT JOIN schedule s ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
        GROUP BY r.id
    """, EXCLUDED_BUILDINGS).fetchall()

    room_list = []
    for r in rows:
        occupied = r["occupied_slots"]
        load_pct = round(occupied / SLOTS_PER_ROOM * 100, 1) if SLOTS_PER_ROOM > 0 else 0
        room_list.append({
            "name": r["name"],
            "building": r["building"],
            "capacity": r["capacity"],
            "has_computers": bool(r["has_computers"]),
            "occupied_slots": occupied,
            "total_slots": SLOTS_PER_ROOM,
            "load_pct": load_pct,
        })

    room_list.sort(key=lambda x: x["load_pct"], reverse=True)

    most = room_list[:n]
    least_candidates = [r for r in room_list if r["occupied_slots"] > 0]
    least_candidates.sort(key=lambda x: x["load_pct"])
    least = least_candidates[:n]

    avg_load = round(sum(r["load_pct"] for r in room_list) / len(room_list), 1) if room_list else 0

    conn.close()

    return {
        "most_loaded": most,
        "least_loaded": least,
        "avg_load": avg_load,
        "total_rooms": len(room_list),
        "empty_rooms": sum(1 for r in room_list if r["occupied_slots"] == 0),
    }


SLOTS = [
    {"name": "1-я (09:00)", "start": "09:00", "end": "10:35"},
    {"name": "2-я (10:50)", "start": "10:50", "end": "12:25"},
    {"name": "3-я (12:40)", "start": "12:40", "end": "14:15"},
    {"name": "4-я (14:30)", "start": "14:30", "end": "16:05"},
    {"name": "5-я (16:20)", "start": "16:20", "end": "17:55"},
    {"name": "6-я (18:00)", "start": "18:00", "end": "19:25"},
    {"name": "7-я (19:35)", "start": "19:35", "end": "21:00"},
]


def load_by_slot() -> list[dict]:
    """Загрузка аудиторий по парам: % занятых аудиторий для каждого (день, пара)."""
    conn = _connect()

    total_rooms = conn.execute("""
        SELECT COUNT(*) as cnt FROM rooms WHERE building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    if total_rooms == 0:
        conn.close()
        return []

    rows = conn.execute("""
        SELECT s.weekday, s.start, s.week_type,
               COUNT(DISTINCT s.room_id) as occupied
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
        GROUP BY s.weekday, s.start, s.week_type
    """, EXCLUDED_BUILDINGS).fetchall()

    conn.close()

    weekday_order = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

    data = {}
    for r in rows:
        wd = r["weekday"]
        start = r["start"][11:16] if len(r["start"]) > 5 else r["start"]
        key = (wd, start)
        if key not in data or r["occupied"] > data[key]:
            data[key] = r["occupied"]

    result = []
    for wd in weekday_order:
        for sl in SLOTS:
            occupied = data.get((wd, sl["start"]), 0)
            pct = round(occupied / total_rooms * 100, 1)
            result.append({
                "weekday": wd,
                "slot": sl["name"],
                "occupied": occupied,
                "total": total_rooms,
                "load_pct": pct,
            })
    return result
