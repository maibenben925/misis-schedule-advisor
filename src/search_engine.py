"""
Шаг 2. Модуль поиска свободных аудиторий (Basic Search).

Функции:
- get_free_rooms(...) — все аудитории, свободные в заданный слот времени.
- get_valid_alternatives(schedule_id) — подходящие альтернативы для проблемного занятия.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_free_rooms(
    weekday: str,
    start: str,
    end: str,
    week_type: str,
    *,
    exclude_room_id: int | None = None,
    booking_date: str | None = None,
) -> list[sqlite3.Row]:
    """
    Возвращает список аудиторий, которые НЕ заняты в указанный слот времени.

    Занятость определяется с учётом:
    - базового расписания (schedule)
    - переносов (transfers): IN — аудитория занята, OUT — аудитория свободна
    - бронирований мероприятий (event_bookings)

    Если указан booking_date (YYYY-MM-DD), проверка точная по дате:
    - расписание минус перенесённые OUT на эту дату
    - плюс перенесённые IN на эту дату
    - плюс бронирования на эту дату

    Если booking_date не указан, проверка по паттерну (weekday + week_type):
    - базовое расписание + перенесённые IN + бронирования (консервативно).
    """
    conn = _connect()

    start_hhmm = start[11:16] if len(start) > 16 else start
    end_hhmm = end[11:16] if len(end) > 16 else end

    if booking_date is not None:
        query = """
            SELECT r.id, r.name, r.building, r.floor,
                   r.capacity, r.has_projector, r.has_computers
            FROM rooms r
            WHERE r.building NOT IN ('Онлайн', 'Каф. ИЯКТ', 'Спортивный комплекс Беляево')
            AND r.id NOT IN (
                SELECT s.room_id FROM schedule s
                WHERE s.weekday = ? AND s.week_type = ?
                  AND s.start < ? AND s.end > ?
                  AND s.id NOT IN (
                      SELECT t.schedule_id FROM transfers t
                      WHERE t.booking_date = ?
                  )
                UNION
                SELECT t.new_room_id FROM transfers t
                WHERE t.booking_date = ? AND t.weekday = ? AND t.week_type = ?
                  AND t.start < ? AND t.end > ?
                UNION
                SELECT eb.room_id FROM event_bookings eb
                WHERE eb.booking_date = ?
                  AND substr(eb.start,12,5) < ? AND substr(eb.end,12,5) > ?
            )
        """
        params = [
            weekday, week_type, end, start,
            booking_date,
            booking_date, weekday, week_type, end, start,
            booking_date, end_hhmm, start_hhmm,
        ]
    else:
        query = """
            SELECT r.id, r.name, r.building, r.floor,
                   r.capacity, r.has_projector, r.has_computers
            FROM rooms r
            WHERE r.building NOT IN ('Онлайн', 'Каф. ИЯКТ', 'Спортивный комплекс Беляево')
            AND r.id NOT IN (
                SELECT s.room_id FROM schedule s
                WHERE s.weekday = ? AND s.week_type = ?
                  AND s.start < ? AND s.end > ?
                UNION
                SELECT DISTINCT t.new_room_id FROM transfers t
                WHERE t.weekday = ? AND t.week_type = ?
                  AND t.start < ? AND t.end > ?
                UNION
                SELECT DISTINCT eb.room_id FROM event_bookings eb
                WHERE eb.weekday = ? AND eb.week_type = ?
                  AND substr(eb.start,12,5) < ? AND substr(eb.end,12,5) > ?
            )
        """
        params = [
            weekday, week_type, end, start,
            weekday, week_type, end, start,
            weekday, week_type, end_hhmm, start_hhmm,
        ]

    if exclude_room_id is not None:
        query += " AND r.id != ?"
        params.append(exclude_room_id)

    query += " ORDER BY r.building, r.name"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_lesson_info(schedule_id: int) -> sqlite3.Row | None:
    """
    Возвращает полную информацию о занятии из расписания:
    lesson, group, room, weekday, start, end, week_type,
    а также students_count и требования к оборудованию.
    """
    conn = _connect()
    row = conn.execute("""
        SELECT
            s.id            AS schedule_id,
            s.weekday,
            s.start,
            s.end,
            s.week_type,

            l.id            AS lesson_id,
            l.title         AS lesson_title,
            l.lesson_type,
            l.teacher,
            l.needs_projector,
            l.needs_computers,

            g.id            AS group_id,
            g.name          AS group_name,
            g.students_count,

            r.id            AS room_id,
            r.name          AS room_name,
            r.building      AS room_building,
            r.floor         AS room_floor,
            r.capacity      AS room_capacity,
            r.has_projector AS room_has_projector,
            r.has_computers AS room_has_computers

        FROM schedule s
        JOIN lessons  l ON s.lesson_id  = l.id
        JOIN groups   g ON s.group_id   = g.id
        JOIN rooms    r ON s.room_id    = r.id
        WHERE s.id = ?
    """, (schedule_id,)).fetchone()
    conn.close()
    return row


def filter_rooms(
    rooms: list[sqlite3.Row],
    students_count: int,
    needs_projector: bool,
    needs_computers: bool,
) -> list[sqlite3.Row]:
    """
    Жёсткая фильтрация (Hard Constraints):
    - capacity >= students_count
    - has_projector если занятие требует
    - has_computers если занятие требует
    """
    result = []
    for r in rooms:
        if r["capacity"] < students_count:
            continue
        if needs_projector and not r["has_projector"]:
            continue
        if needs_computers and not r["has_computers"]:
            continue
        result.append(r)
    return result


def get_valid_alternatives(schedule_id: int) -> list[sqlite3.Row]:
    """
    Для проблемного занятия (schedule_id) находит все подходящие свободные аудитории.

    Алгоритм:
    1. Берём информацию о занятии (студенты, оборудование, время).
    2. Находим все свободные в это время аудитории.
    3. Фильтруем по вместимости и оборудованию (Hard Constraints).
    4. Возвращаем список подходящих аудиторий.
    """
    info = get_lesson_info(schedule_id)
    if info is None:
        raise ValueError(f"Занятие schedule_id={schedule_id} не найдено")

    free_rooms = get_free_rooms(
        weekday=info["weekday"],
        start=info["start"],
        end=info["end"],
        week_type=info["week_type"],
        exclude_room_id=info["room_id"],
    )

    valid = filter_rooms(
        rooms=free_rooms,
        students_count=info["students_count"],
        needs_projector=bool(info["needs_projector"]),
        needs_computers=bool(info["needs_computers"]),
    )

    return valid


def find_room_for_event(
    capacity: int,
    needs_projector: bool,
    needs_computers: bool,
    weekday: str,
    start: str,
    end: str,
    week_type: str,
    top_n: int = 5,
    booking_date: str | None = None,
) -> list[sqlite3.Row]:
    """
    Найти лучшие аудитории для внеучебного мероприятия.

    Возвращает топ-N аудиторий, отсортированных по минимальному
    избытку вместимости (ближе к requested capacity — лучше).

    Если указан booking_date, поиск учитывает переносы и бронирования
    на конкретную дату.
    """
    free_rooms = get_free_rooms(weekday, start, end, week_type, booking_date=booking_date)

    # Моковые данные: у мероприятия нет группы, поэтому students_count = capacity
    valid = filter_rooms(free_rooms, capacity, needs_projector, needs_computers)

    # Сортировка: чем меньше «лишних» мест, тем лучше
    valid.sort(key=lambda r: r["capacity"] - capacity)

    return valid[:top_n]


# ──────────────────────────────────────────────
# CLI-тест
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import random

    conn = _connect()
    sample_ids = [r["id"] for r in conn.execute("SELECT id FROM schedule LIMIT 20").fetchall()]
    conn.close()

    sid = random.choice(sample_ids)
    print(f"=== Тест: schedule_id={sid} ===\n")

    info = get_lesson_info(sid)
    print(f"Занятие:   {info['lesson_title']}")
    print(f"Тип:       {info['lesson_type']}")
    print(f"Группа:    {info['group_name']} ({info['students_count']} чел.)")
    print(f"Время:     {info['weekday']}, {info['start'][11:16]}–{info['end'][11:16]}, {info['week_type']}")
    print(f"Текущая:   {info['room_name']} (корп.{info['room_building']}, эт.{info['room_floor']}, cap={info['room_capacity']})")
    print(f"Нужно:     проектор={'да' if info['needs_projector'] else 'нет'}, компьютеры={'да' if info['needs_computers'] else 'нет'}")

    alts = get_valid_alternatives(sid)
    print(f"\nНайдено подходящих альтернатив: {len(alts)}")
    for i, r in enumerate(alts[:10], 1):
        print(f"  {i:2d}. {r['name']:15s} | {r['building']:5s} эт.{r['floor']} | cap={r['capacity']:3d} | "
              f"proj={r['has_projector']} comp={r['has_computers']}")
    if len(alts) > 10:
        print(f"  ... и ещё {len(alts) - 10}")
