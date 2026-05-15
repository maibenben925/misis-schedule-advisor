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


def pc_utilization() -> dict:
    """Использование компьютерных классов.

    ПК — дефицитный ресурс: лабораторные требуют ПК, но компьютерные классы
    часто заняты обычными занятиями. Проекторы не дефицит — не учитываем.
    """
    conn = _connect()

    comp_rooms_total = conn.execute("""
        SELECT COUNT(*) as cnt FROM rooms
        WHERE has_computers = 1 AND building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    comp_rooms_for_comp = conn.execute("""
        SELECT COUNT(DISTINCT s.room_id) as cnt
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE r.has_computers = 1 AND r.building NOT IN (?,?,?)
          AND l.needs_computers = 1
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    comp_rooms_for_noncomp = conn.execute("""
        SELECT COUNT(DISTINCT s.room_id) as cnt
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE r.has_computers = 1 AND r.building NOT IN (?,?,?)
          AND l.needs_computers = 0
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    comp_slots_for_comp = conn.execute("""
        SELECT COUNT(*) as cnt
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE r.has_computers = 1 AND r.building NOT IN (?,?,?)
          AND l.needs_computers = 1
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    comp_slots_for_noncomp = conn.execute("""
        SELECT COUNT(*) as cnt
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE r.has_computers = 1 AND r.building NOT IN (?,?,?)
          AND l.needs_computers = 0
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    comp_rooms_wasted = conn.execute("""
        SELECT r.name, r.building, r.capacity,
               COUNT(*) as total_slots,
               SUM(CASE WHEN l.needs_computers = 0 THEN 1 ELSE 0 END) as wasted_slots
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE r.has_computers = 1 AND r.building NOT IN (?,?,?)
        GROUP BY r.id
        HAVING wasted_slots > 0
        ORDER BY wasted_slots DESC
        LIMIT 10
    """, EXCLUDED_BUILDINGS).fetchall()

    lessons_needing_pc = conn.execute("""
        SELECT COUNT(*) as cnt FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN rooms r ON s.room_id = r.id
        WHERE l.needs_computers = 1 AND r.building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    conn.close()

    return {
        "rooms_total": comp_rooms_total,
        "rooms_for_comp": comp_rooms_for_comp,
        "rooms_for_noncomp": comp_rooms_for_noncomp,
        "slots_for_comp": comp_slots_for_comp,
        "slots_for_noncomp": comp_slots_for_noncomp,
        "lessons_needing_pc": lessons_needing_pc,
        "wasted_rooms": [dict(r) for r in comp_rooms_wasted],
    }


def capacity_demand() -> list[dict]:
    """Загрузка по вместимости: слоты заняты vs слоты доступны.

    Считает суммарное число студентов на занятии, объединяя группы
    потоковых лекций. Показывает переполнение — занятия, которым нужна
    эта категория, но стоят в большей (из-за отсутствия подходящей).
    """
    conn = _connect()
    SLOTS_PER_ROOM = 84  # 6 дней × 7 пар × 2 недели

    ranges = [
        {"label": "до 20", "min": 0, "max": 20},
        {"label": "20–40", "min": 20, "max": 40},
        {"label": "40–60", "min": 40, "max": 60},
        {"label": "60–80", "min": 60, "max": 80},
        {"label": "80–100", "min": 80, "max": 100},
        {"label": "100+", "min": 100, "max": 9999},
    ]

    lesson_sizes = conn.execute("""
        SELECT s.lesson_id, s.weekday, s.start, s.week_type,
               SUM(g.students_count) as total_students
        FROM schedule s
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
        GROUP BY s.lesson_id, s.weekday, s.start, s.week_type
    """, EXCLUDED_BUILDINGS).fetchall()

    size_counts = {}
    overflow = {}
    for r in lesson_sizes:
        total = r["total_students"]
        placed = False
        for rng in ranges:
            if rng["min"] < total <= rng["max"]:
                size_counts[rng["label"]] = size_counts.get(rng["label"], 0) + 1
                placed = True
                break
        if not placed:
            size_counts[ranges[-1]["label"]] = size_counts.get(ranges[-1]["label"], 0) + 1

    room_occupied = conn.execute("""
        SELECT
            CASE
                WHEN capacity <= 20 THEN "до 20"
                WHEN capacity <= 40 THEN "20–40"
                WHEN capacity <= 60 THEN "40–60"
                WHEN capacity <= 80 THEN "60–80"
                WHEN capacity <= 100 THEN "80–100"
                ELSE "100+"
            END as rng,
            COUNT(DISTINCT s.room_id) as rooms_with_lessons,
            COUNT(DISTINCT s.room_id || s.weekday || s.start || s.week_type) as occupied_slots
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
        GROUP BY rng
    """, EXCLUDED_BUILDINGS).fetchall()

    occupied_map = {r["rng"]: dict(r) for r in room_occupied}

    results = []
    for rng in ranges:
        n_rooms = conn.execute("""
            SELECT COUNT(*) as cnt FROM rooms
            WHERE building NOT IN (?,?,?)
              AND capacity > ? AND capacity <= ?
        """, (*EXCLUDED_BUILDINGS, rng["min"], rng["max"])).fetchone()["cnt"]

        total_slots = n_rooms * SLOTS_PER_ROOM
        occ = occupied_map.get(rng["label"], {})
        occupied = occ.get("occupied_slots", 0)
        load_pct = round(occupied / total_slots * 100, 1) if total_slots > 0 else 0
        free = total_slots - occupied

        lessons_in_range = size_counts.get(rng["label"], 0)

        overflow_count = 0
        if n_rooms == 0 and lessons_in_range > 0:
            overflow_count = lessons_in_range

        results.append({
            "range": rng["label"],
            "rooms": n_rooms,
            "total_slots": total_slots,
            "occupied_slots": occupied,
            "free_slots": free,
            "load_pct": load_pct,
            "lessons_in_range": lessons_in_range,
            "overflow": overflow_count,
        })

    conn.close()
    return results


def transfer_destinations(n: int = 10) -> dict:
    """Аудитории, которые чаще всего получают перенесённые занятия.
    Это «рабочие лошадки» — их закрытие критично для системы."""
    conn = _connect()

    total = conn.execute("SELECT COUNT(*) as cnt FROM transfers").fetchone()["cnt"]

    top = conn.execute("""
        SELECT r.name, r.building, r.capacity,
               COUNT(*) as transfer_count,
               COUNT(DISTINCT t.booking_date) as dates_affected
        FROM transfers t
        JOIN rooms r ON t.new_room_id = r.id
        GROUP BY t.new_room_id
        ORDER BY transfer_count DESC
        LIMIT ?
    """, (n,)).fetchall()

    conn.close()

    return {
        "total_transfers": total,
        "top_rooms": [dict(r) for r in top],
    }



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
        SELECT COUNT(*) as cnt FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    n_unique_lesson_slots = conn.execute("""
        SELECT COUNT(*) as cnt FROM (
            SELECT DISTINCT s.lesson_id, s.weekday, s.start, s.week_type
            FROM schedule s
            JOIN rooms r ON s.room_id = r.id
            WHERE r.building NOT IN (?,?,?)
        )
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    n_groups = conn.execute("""
        SELECT COUNT(DISTINCT s.group_id) as cnt FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    total_capacity = conn.execute("""
        SELECT SUM(capacity) as cnt FROM rooms WHERE building NOT IN (?,?,?)
    """, EXCLUDED_BUILDINGS).fetchone()["cnt"]

    total_bookings = conn.execute("SELECT COUNT(*) as cnt FROM event_bookings").fetchone()["cnt"]
    total_transfers = conn.execute("SELECT COUNT(*) as cnt FROM transfers").fetchone()["cnt"]
    transfer_dates = conn.execute("SELECT COUNT(DISTINCT booking_date) as cnt FROM transfers").fetchone()["cnt"]
    transfer_rooms = conn.execute("SELECT COUNT(DISTINCT new_room_id) as cnt FROM transfers").fetchone()["cnt"]

    try:
        total_cancellations = conn.execute("SELECT COUNT(*) as cnt FROM cancellations WHERE is_restored = 0").fetchone()["cnt"]
        cancel_dates = conn.execute("SELECT COUNT(DISTINCT cancel_date) as cnt FROM cancellations WHERE is_restored = 0").fetchone()["cnt"]
    except sqlite3.OperationalError:
        total_cancellations = 0
        cancel_dates = 0

    conn.close()

    return {
        "rooms": n_rooms,
        "buildings": n_buildings,
        "schedule_entries": n_lessons,
        "unique_lesson_slots": n_unique_lesson_slots,
        "groups": n_groups,
        "total_capacity": total_capacity or 0,
        "bookings": total_bookings,
        "transfers": total_transfers,
        "transfer_dates": transfer_dates,
        "transfer_rooms": transfer_rooms,
        "cancellations": total_cancellations,
        "cancel_dates": cancel_dates,
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
