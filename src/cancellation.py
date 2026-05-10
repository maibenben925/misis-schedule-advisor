from __future__ import annotations

import sqlite3
import os
from dataclasses import dataclass
from datetime import date, timedelta
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

SLOTS = [
    {"name": "1-я пара", "start": "09:00", "end": "10:35"},
    {"name": "2-я пара", "start": "10:50", "end": "12:25"},
    {"name": "3-я пара", "start": "12:40", "end": "14:15"},
    {"name": "4-я пара", "start": "14:30", "end": "16:05"},
    {"name": "5-я пара", "start": "16:20", "end": "17:55"},
    {"name": "6-я пара", "start": "18:00", "end": "19:25"},
    {"name": "7-я пара", "start": "19:35", "end": "21:00"},
]

BASE_MONDAY = date(2026, 1, 12)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _d2wt(d: date) -> str:
    diff = (d - BASE_MONDAY).days
    return "upper" if (diff // 7) % 2 == 0 else "lower"


def _d2wd(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def _to_iso(t: str, d: date | str | None = None) -> str:
    dt = str(d) if d else "2026-01-12"
    return f"{dt}T{t}:00+03:00"


def _slot_index(start: str) -> int:
    s = start[11:16] if len(start) > 5 else start
    for i, sl in enumerate(SLOTS):
        if sl["start"] == s:
            return i
    return -1


def ensure_cancellations_table():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cancellations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            cancel_date TEXT NOT NULL,
            reason TEXT,
            is_restored BOOLEAN DEFAULT 0,
            restored_schedule_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES schedule(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cancellations_date ON cancellations(cancel_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cancellations_schedule ON cancellations(schedule_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cancellations_restored ON cancellations(is_restored)")
    conn.commit()
    conn.close()


@dataclass
class CancelPreview:
    schedule_id: int
    lesson_title: str
    lesson_type: str
    teacher: str
    group_name: str
    room_name: str
    weekday: str
    start: str
    end: str
    cancel_date: str


@dataclass
class RestoreSlot:
    weekday: str
    start: str
    end: str
    week_type: str
    room_id: int
    room_name: str
    room_building: str
    room_floor: int
    room_capacity: int
    penalty: int
    match_percent: float
    restore_date: str = ""


def _find_lessons_by_teacher(teacher: str, date_from: date, date_to: date) -> list[dict]:
    conn = _connect()
    rows = conn.execute("""
        SELECT s.id AS schedule_id, s.weekday, s.start, s.end, s.week_type,
               l.id AS lesson_id, l.title, l.lesson_type, l.teacher,
               g.name AS group_name, g.students_count,
               r.name AS room_name, r.building AS room_building, r.floor AS room_floor,
               r.capacity AS room_capacity
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE l.teacher LIKE ?
    """, (f"%{teacher}%",)).fetchall()
    conn.close()

    dates_by_key = defaultdict(list)
    d = date_from
    while d <= date_to:
        dates_by_key[(_d2wd(d), _d2wt(d))].append(d)
        d += timedelta(days=1)

    result = []
    for row in rows:
        key = (row["weekday"], row["week_type"])
        for dt in dates_by_key.get(key, []):
            result.append({**dict(row), "cancel_date": str(dt)})
    return result


def _find_lessons_by_discipline(lesson_title: str, date_from: date, date_to: date) -> list[dict]:
    conn = _connect()
    rows = conn.execute("""
        SELECT s.id AS schedule_id, s.weekday, s.start, s.end, s.week_type,
               l.id AS lesson_id, l.title, l.lesson_type, l.teacher,
               g.name AS group_name, g.students_count,
               r.name AS room_name, r.building AS room_building, r.floor AS room_floor,
               r.capacity AS room_capacity
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE l.title LIKE ?
    """, (f"%{lesson_title}%",)).fetchall()
    conn.close()

    dates_by_key = defaultdict(list)
    d = date_from
    while d <= date_to:
        dates_by_key[(_d2wd(d), _d2wt(d))].append(d)
        d += timedelta(days=1)

    result = []
    for row in rows:
        key = (row["weekday"], row["week_type"])
        for dt in dates_by_key.get(key, []):
            result.append({**dict(row), "cancel_date": str(dt)})
    return result


def _find_single_lesson(schedule_id: int, cancel_date: date) -> dict | None:
    conn = _connect()
    row = conn.execute("""
        SELECT s.id AS schedule_id, s.weekday, s.start, s.end, s.week_type,
               l.id AS lesson_id, l.title, l.lesson_type, l.teacher,
               g.name AS group_name, g.students_count,
               r.name AS room_name, r.building AS room_building, r.floor AS room_floor,
               r.capacity AS room_capacity
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE s.id = ?
    """, (schedule_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {**dict(row), "cancel_date": str(cancel_date)}


def _to_previews(rows: list[dict]) -> list[CancelPreview]:
    conn = _connect()
    existing = set()
    for r in rows:
        eid = conn.execute(
            "SELECT id FROM cancellations WHERE schedule_id = ? AND cancel_date = ? AND is_restored = 0",
            (r["schedule_id"], r["cancel_date"]),
        ).fetchone()
        if eid:
            existing.add((r["schedule_id"], r["cancel_date"]))
    conn.close()

    previews = []
    for r in rows:
        if (r["schedule_id"], r["cancel_date"]) in existing:
            continue
        previews.append(CancelPreview(
            schedule_id=r["schedule_id"],
            lesson_title=r["title"],
            lesson_type=r["lesson_type"],
            teacher=r["teacher"] or "",
            group_name=r["group_name"],
            room_name=r["room_name"],
            weekday=r["weekday"],
            start=r["start"][11:16] if len(r["start"]) > 5 else r["start"],
            end=r["end"][11:16] if len(r["end"]) > 5 else r["end"],
            cancel_date=r["cancel_date"],
        ))
    return previews


def preview_cancel_by_teacher(teacher: str, date_from: date, date_to: date) -> list[CancelPreview]:
    rows = _find_lessons_by_teacher(teacher, date_from, date_to)
    return _to_previews(rows)


def preview_cancel_by_discipline(lesson_title: str, date_from: date, date_to: date) -> list[CancelPreview]:
    rows = _find_lessons_by_discipline(lesson_title, date_from, date_to)
    return _to_previews(rows)


def preview_cancel_single(schedule_id: int, cancel_date: date) -> list[CancelPreview]:
    row = _find_single_lesson(schedule_id, cancel_date)
    if row is None:
        return []
    conn = _connect()
    lesson_id = row["lesson_id"]
    same_slot = conn.execute("""
        SELECT s.id AS schedule_id, s.weekday, s.start, s.end, s.week_type,
               l.id AS lesson_id, l.title, l.lesson_type, l.teacher,
               g.name AS group_name, g.students_count,
               r.name AS room_name, r.building AS room_building, r.floor AS room_floor,
               r.capacity AS room_capacity
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE l.id = ? AND s.weekday = ? AND s.start = ? AND s.week_type = ?
    """, (lesson_id, row["weekday"], row["start"], row["week_type"])).fetchall()
    conn.close()
    return _to_previews([{**dict(r), "cancel_date": str(cancel_date)} for r in same_slot])


def apply_cancels(previews: list[CancelPreview], reason: str) -> int:
    conn = _connect()
    count = 0
    for p in previews:
        existing = conn.execute(
            "SELECT id FROM cancellations WHERE schedule_id = ? AND cancel_date = ? AND is_restored = 0",
            (p.schedule_id, p.cancel_date),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO cancellations (schedule_id, cancel_date, reason) VALUES (?, ?, ?)",
            (p.schedule_id, p.cancel_date, reason),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def get_cancellations(
    date_from: date | None = None,
    date_to: date | None = None,
    is_restored: bool | None = None,
) -> list[sqlite3.Row]:
    conn = _connect()
    q = """
        SELECT c.id, c.schedule_id, c.cancel_date, c.reason,
               c.is_restored, c.restored_schedule_id, c.created_at,
               s.weekday, s.start, s.end, s.week_type,
               l.title AS lesson_title, l.lesson_type, l.teacher,
               g.name AS group_name, g.students_count,
               r.name AS room_name, r.building, r.floor,
               rs.weekday AS restored_weekday,
               rs.start AS restored_start, rs.end AS restored_end,
               rs.week_type AS restored_week_type,
               rr.name AS restored_room_name,
               rr.building AS restored_building,
               rr.floor AS restored_floor
        FROM cancellations c
        JOIN schedule s ON c.schedule_id = s.id
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        LEFT JOIN schedule rs ON c.restored_schedule_id = rs.id
        LEFT JOIN rooms rr ON rs.room_id = rr.id
        WHERE 1=1
    """
    params: list = []
    if date_from is not None:
        q += " AND c.cancel_date >= ?"
        params.append(str(date_from))
    if date_to is not None:
        q += " AND c.cancel_date <= ?"
        params.append(str(date_to))
    if is_restored is not None:
        q += " AND c.is_restored = ?"
        params.append(int(is_restored))
    q += " ORDER BY c.created_at DESC, s.start"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def get_active_cancellations_for_date(sel_date: date) -> list[sqlite3.Row]:
    conn = _connect()
    rows = conn.execute("""
        SELECT c.id, c.schedule_id, c.cancel_date, c.reason,
               c.is_restored, c.restored_schedule_id,
               s.weekday, s.start, s.end, s.week_type,
               l.title AS lesson_title, l.lesson_type, l.teacher,
               g.name AS group_name,
               r.name AS room_name, r.id AS room_id
        FROM cancellations c
        JOIN schedule s ON c.schedule_id = s.id
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE c.cancel_date = ? AND c.is_restored = 0
    """, (str(sel_date),)).fetchall()
    conn.close()
    return rows


def get_restored_for_date(sel_date: date) -> list[sqlite3.Row]:
    conn = _connect()
    rows = conn.execute("""
        SELECT c.id, c.schedule_id, c.cancel_date, c.reason,
               c.restored_schedule_id,
               rs.weekday, rs.start, rs.end, rs.week_type,
               l.title AS lesson_title, l.lesson_type, l.teacher,
               g.name AS group_name,
               r.name AS room_name, r.id AS room_id
        FROM cancellations c
        JOIN schedule rs ON c.restored_schedule_id = rs.id
        JOIN lessons l ON rs.lesson_id = l.id
        JOIN groups g ON rs.group_id = g.id
        JOIN rooms r ON rs.room_id = r.id
        WHERE c.is_restored = 1
          AND rs.weekday = ? AND rs.week_type = ?
    """, (_d2wd(sel_date), _d2wt(sel_date))).fetchall()
    conn.close()
    return rows


def _slot_busy_for_groups_conn(conn, group_ids, weekday, start, end, week_type, cancel_date):
    ph = ",".join("?" for _ in group_ids)
    q = f"""
        SELECT COUNT(*) as cnt FROM schedule s
        WHERE s.group_id IN ({ph}) AND s.weekday = ? AND s.week_type = ?
          AND s.start < ? AND s.end > ?
          AND s.id NOT IN (
              SELECT c.schedule_id FROM cancellations c
              WHERE c.cancel_date = ? AND c.is_restored = 0
          )
    """
    params = list(group_ids) + [weekday, week_type, _to_iso(end), _to_iso(start), cancel_date]
    cnt = conn.execute(q, params).fetchone()["cnt"]
    return cnt > 0


def _teacher_busy_conn(conn, teacher: str, weekday: str, start: str, end: str,
                       week_type: str, cancel_date: str) -> bool:
    rows = conn.execute("""
        SELECT s.id FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        WHERE l.teacher LIKE ? AND s.weekday = ? AND s.week_type = ?
          AND s.start < ? AND s.end > ?
          AND s.id NOT IN (
              SELECT c.schedule_id FROM cancellations c
              WHERE c.cancel_date = ? AND c.is_restored = 0
          )
    """, (f"%{teacher}%", weekday, week_type,
          _to_iso(end), _to_iso(start), cancel_date)).fetchall()
    return len(rows) > 0


def _get_free_rooms_for_restore_conn(conn, weekday, start, end, week_type,
                                      needs_projector, needs_computers,
                                      students_count, booking_date,
                                      orig_building="", orig_floor=0) -> list[dict]:
    from .search_engine import get_free_rooms
    start_iso = _to_iso(start)
    end_iso = _to_iso(end)
    free = get_free_rooms(weekday, start_iso, end_iso, week_type, booking_date=booking_date)

    result = []
    from .scoring import calculate_penalty
    for r in free:
        if r["capacity"] < students_count:
            continue
        if needs_projector and not r["has_projector"]:
            continue
        if needs_computers and not r["has_computers"]:
            continue
        penalty = calculate_penalty(
            original_building=orig_building,
            original_floor=orig_floor,
            alt_building=r["building"],
            alt_floor=r["floor"],
            alt_capacity=r["capacity"],
            students_count=students_count,
            needs_projector=bool(needs_projector),
            needs_computers=bool(needs_computers),
            alt_has_projector=bool(r["has_projector"]),
            alt_has_computers=bool(r["has_computers"]),
        )
        result.append({
            "room_id": r["id"],
            "room_name": r["name"],
            "room_building": r["building"],
            "room_floor": r["floor"],
            "room_capacity": r["capacity"],
            "penalty": penalty,
        })
    return result


def _is_reserved(reserved: list[dict], group_ids, weekday, start, end, room_id=None) -> bool:
    for r in reserved:
        if r["weekday"] == weekday and r["start"] == start and r["end"] == end:
            if r["group_id"] in group_ids:
                return True
            if room_id is not None and r["room_id"] == room_id:
                return True
    return False


def _find_restore_candidates_conn(conn, row, group_ids, teacher, cancel_dt,
                                  orig_wd_idx, orig_slot_idx,
                                  start_from: date, search_days: int = 10,
                                  reserved: list[dict] | None = None) -> list[RestoreSlot]:
    if reserved is None:
        reserved = []
    candidates: list[RestoreSlot] = []
    d = start_from
    end_d = start_from + timedelta(days=search_days)
    workdays_checked = 0

    while d <= end_d and workdays_checked < 10:
        wd = _d2wd(d)
        wt = _d2wt(d)
        if d.weekday() >= 6:
            d += timedelta(days=1)
            continue

        workdays_checked += 1
        days_from_start = (d - start_from).days

        for sl in SLOTS:
            if _slot_busy_for_groups_conn(conn, group_ids=group_ids, weekday=wd,
                                          start=sl["start"], end=sl["end"], week_type=wt,
                                          cancel_date=str(d)):
                continue
            if _is_reserved(reserved, group_ids, wd, sl["start"], sl["end"]):
                continue
            if teacher and _teacher_busy_conn(conn, teacher, wd, sl["start"], sl["end"], wt, str(d)):
                continue

            free_rooms = _get_free_rooms_for_restore_conn(
                conn, wd, sl["start"], sl["end"], wt, row["needs_projector"],
                row["needs_computers"], row["students_count"], str(d),
                orig_building=row["orig_building"], orig_floor=row["orig_floor"],
            )
            if not free_rooms:
                continue

            best_room = min(free_rooms, key=lambda r: r["penalty"])
            if _is_reserved(reserved, set(), wd, sl["start"], sl["end"], best_room["room_id"]):
                free_rooms_filtered = [fr for fr in free_rooms
                                       if not _is_reserved(reserved, set(), wd, sl["start"], sl["end"], fr["room_id"])]
                if not free_rooms_filtered:
                    continue
                best_room = min(free_rooms_filtered, key=lambda r: r["penalty"])

            cand_wd_idx = WEEKDAYS.index(wd)
            cand_slot_idx = _slot_index(sl["start"])

            day_diff = abs(cand_wd_idx - orig_wd_idx)
            day_diff = min(day_diff, 7 - day_diff)
            time_diff = abs(cand_slot_idx - orig_slot_idx)

            room_penalty = best_room["penalty"]
            schedule_penalty = day_diff * 50 + time_diff * 5
            proximity_penalty = days_from_start * 30
            total_penalty = room_penalty + schedule_penalty + proximity_penalty

            candidates.append(RestoreSlot(
                weekday=wd,
                start=sl["start"],
                end=sl["end"],
                week_type=wt,
                room_id=best_room["room_id"],
                room_name=best_room["room_name"],
                room_building=best_room["room_building"],
                room_floor=best_room["room_floor"],
                room_capacity=best_room["room_capacity"],
                penalty=total_penalty,
                match_percent=0.0,
                restore_date=str(d),
            ))

        d += timedelta(days=1)

    return candidates


def _find_sibling_cancellations(lesson_id: int, cancel_date: str,
                                weekday: str, start: str, week_type: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute("""
        SELECT c.schedule_id, s.group_id
        FROM cancellations c
        JOIN schedule s ON c.schedule_id = s.id
        WHERE c.cancel_date = ? AND c.is_restored = 0
          AND s.lesson_id = ? AND s.weekday = ? AND s.start = ? AND s.week_type = ?
    """, (cancel_date, lesson_id, weekday, start, week_type)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_restore_slots(cancellation_id: int, search_days: int = 10) -> list[RestoreSlot]:
    conn = _connect()
    row = conn.execute("""
        SELECT c.schedule_id, c.cancel_date,
               s.weekday, s.start, s.end, s.week_type,
               s.lesson_id, s.group_id, s.room_id,
               l.title, l.lesson_type, l.teacher,
               l.needs_projector, l.needs_computers,
               g.students_count,
               r.building AS orig_building, r.floor AS orig_floor
        FROM cancellations c
        JOIN schedule s ON c.schedule_id = s.id
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE c.id = ?
    """, (cancellation_id,)).fetchone()
    conn.close()

    if row is None:
        return []

    cancel_dt = date.fromisoformat(row["cancel_date"])
    orig_wd_idx = WEEKDAYS.index(row["weekday"])
    orig_slot_idx = _slot_index(row["start"])

    all_cancellations_for_lesson = _find_sibling_cancellations(
        row["lesson_id"], row["cancel_date"],
        row["weekday"], row["start"], row["week_type"],
    )

    group_ids = set(c["group_id"] for c in all_cancellations_for_lesson)
    teacher = row["teacher"]

    start_from = max(date.today(), cancel_dt + timedelta(days=1))

    conn2 = _connect()
    candidates = _find_restore_candidates_conn(
        conn2, row, group_ids, teacher, cancel_dt,
        orig_wd_idx, orig_slot_idx,
        start_from, search_days,
    )
    conn2.close()

    if not candidates:
        return []

    min_p = min(c.penalty for c in candidates)
    max_p = max(c.penalty for c in candidates)
    for c in candidates:
        if max_p == min_p:
            c.match_percent = 100.0
        else:
            c.match_percent = round((1 - (c.penalty - min_p) / (max_p - min_p)) * 100, 1)

    candidates.sort(key=lambda c: (c.penalty, -c.match_percent))
    return candidates[:20]


def restore_lesson(cancellation_id: int, slot: RestoreSlot) -> int | None:
    conn = _connect()
    row = conn.execute("""
        SELECT c.schedule_id, s.lesson_id, s.group_id, s.room_id,
               s.weekday, s.start, s.end, s.week_type,
               l.title, l.lesson_type, l.teacher
        FROM cancellations c
        JOIN schedule s ON c.schedule_id = s.id
        JOIN lessons l ON s.lesson_id = l.id
        WHERE c.id = ?
    """, (cancellation_id,)).fetchone()
    if row is None:
        conn.close()
        return None

    cancel_dt = date.fromisoformat(
        conn.execute("SELECT cancel_date FROM cancellations WHERE id = ?",
                     (cancellation_id,)).fetchone()["cancel_date"]
    )

    sibling_cids = _find_sibling_cancellation_ids(
        conn, row["lesson_id"], row["weekday"], row["start"], row["week_type"],
        str(cancel_dt),
    )

    new_schedule_ids = []
    for cid in sibling_cids:
        sid_info = conn.execute("""
            SELECT s.lesson_id, s.group_id FROM cancellations c
            JOIN schedule s ON c.schedule_id = s.id
            WHERE c.id = ?
        """, (cid,)).fetchone()
        if sid_info is None:
            continue

        start_iso = _to_iso(slot.start)
        end_iso = _to_iso(slot.end)

        conn.execute("""
            INSERT INTO schedule (lesson_id, group_id, room_id, weekday, start, end, week_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sid_info["lesson_id"], sid_info["group_id"], slot.room_id,
              slot.weekday, start_iso, end_iso, slot.week_type))
        new_sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        new_schedule_ids.append(new_sid)

        conn.execute("""
            UPDATE cancellations SET is_restored = 1, restored_schedule_id = ?
            WHERE id = ?
        """, (new_sid, cid))

    conn.commit()
    conn.close()
    return new_schedule_ids[0] if new_schedule_ids else None


def mass_restore_preview(cancellation_ids: list[int]) -> list[dict]:
    conn = _connect()
    preview = []
    processed = set()
    reserved: list[dict] = []

    for cid in cancellation_ids:
        if cid in processed:
            continue

        row = conn.execute("""
            SELECT c.schedule_id, c.cancel_date,
                   s.weekday, s.start, s.end, s.week_type,
                   s.lesson_id, s.group_id, s.room_id,
                   l.title, l.lesson_type, l.teacher,
                   l.needs_projector, l.needs_computers,
                   g.students_count, g.name AS group_name,
                   r.building AS orig_building, r.floor AS orig_floor,
                   r.name AS orig_room
            FROM cancellations c
            JOIN schedule s ON c.schedule_id = s.id
            JOIN lessons l ON s.lesson_id = l.id
            JOIN groups g ON s.group_id = g.id
            JOIN rooms r ON s.room_id = r.id
            WHERE c.id = ?
        """, (cid,)).fetchone()

        if row is None:
            continue

        cancel_dt = date.fromisoformat(row["cancel_date"])
        orig_wd_idx = WEEKDAYS.index(row["weekday"])
        orig_slot_idx = _slot_index(row["start"])

        sibling_cids = _find_sibling_cancellation_ids(
            conn, row["lesson_id"], row["weekday"], row["start"], row["week_type"],
            str(cancel_dt),
        )
        for scid in sibling_cids:
            processed.add(scid)

        group_ids = set()
        group_names = []
        for scid in sibling_cids:
            g_row = conn.execute("""
                SELECT s.group_id, g.name AS group_name FROM cancellations c
                JOIN schedule s ON c.schedule_id = s.id
                JOIN groups g ON s.group_id = g.id
                WHERE c.id = ?
            """, (scid,)).fetchone()
            if g_row:
                group_ids.add(g_row["group_id"])
                group_names.append(g_row["group_name"])

        teacher = row["teacher"]
        start_from = max(date.today(), cancel_dt + timedelta(days=1))

        candidates = _find_restore_candidates_conn(
            conn, row, group_ids, teacher, cancel_dt,
            orig_wd_idx, orig_slot_idx,
            start_from, 10,
            reserved=reserved,
        )

        if candidates:
            best = candidates[0]
            for gid in group_ids:
                reserved.append({
                    "group_id": gid,
                    "weekday": best.weekday,
                    "start": best.start,
                    "end": best.end,
                    "room_id": best.room_id,
                })
            preview.append({
                "cancel_id": cid,
                "lesson_title": row["title"],
                "lesson_type": row["lesson_type"],
                "teacher": row["teacher"],
                "group_names": ", ".join(sorted(set(group_names))),
                "cancel_date": str(cancel_dt),
                "orig_weekday": row["weekday"],
                "orig_start": row["start"][11:16] if len(row["start"]) > 5 else row["start"],
                "orig_end": row["end"][11:16] if len(row["end"]) > 5 else row["end"],
                "orig_room": row["orig_room"],
                "new_weekday": best.weekday,
                "new_start": best.start,
                "new_end": best.end,
                "new_room": best.room_name,
                "new_date": best.restore_date,
                "penalty": best.penalty,
                "has_slot": True,
            })
        else:
            preview.append({
                "cancel_id": cid,
                "lesson_title": row["title"],
                "lesson_type": row["lesson_type"],
                "teacher": row["teacher"],
                "group_names": ", ".join(sorted(set(group_names))),
                "cancel_date": str(cancel_dt),
                "orig_weekday": row["weekday"],
                "orig_start": row["start"][11:16] if len(row["start"]) > 5 else row["start"],
                "orig_end": row["end"][11:16] if len(row["end"]) > 5 else row["end"],
                "orig_room": row["orig_room"],
                "new_weekday": "—",
                "new_start": "—",
                "new_end": "—",
                "new_room": "—",
                "new_date": "—",
                "penalty": None,
                "has_slot": False,
            })

    conn.close()
    return preview


def mass_restore(cancellation_ids: list[int]) -> dict:
    conn = _connect()
    results = {"restored": 0, "failed": 0, "no_slots": 0, "details": []}

    processed = set()
    for cid in cancellation_ids:
        if cid in processed:
            continue

        row = conn.execute("""
            SELECT c.schedule_id, c.cancel_date,
                   s.weekday, s.start, s.end, s.week_type,
                   s.lesson_id, s.group_id, s.room_id,
                   l.title, l.lesson_type, l.teacher,
                   l.needs_projector, l.needs_computers,
                   g.students_count, g.name AS group_name,
                   r.building AS orig_building, r.floor AS orig_floor
            FROM cancellations c
            JOIN schedule s ON c.schedule_id = s.id
            JOIN lessons l ON s.lesson_id = l.id
            JOIN groups g ON s.group_id = g.id
            JOIN rooms r ON s.room_id = r.id
            WHERE c.id = ?
        """, (cid,)).fetchone()

        if row is None:
            results["failed"] += 1
            continue

        cancel_dt = date.fromisoformat(row["cancel_date"])
        orig_wd_idx = WEEKDAYS.index(row["weekday"])
        orig_slot_idx = _slot_index(row["start"])

        sibling_cids = _find_sibling_cancellation_ids(
            conn, row["lesson_id"], row["weekday"], row["start"], row["week_type"],
            str(cancel_dt),
        )
        for scid in sibling_cids:
            processed.add(scid)

        group_ids = set()
        for scid in sibling_cids:
            g_row = conn.execute("""
                SELECT s.group_id FROM cancellations c
                JOIN schedule s ON c.schedule_id = s.id
                WHERE c.id = ?
            """, (scid,)).fetchone()
            if g_row:
                group_ids.add(g_row["group_id"])

        teacher = row["teacher"]
        start_from = max(date.today(), cancel_dt + timedelta(days=1))

        candidates = _find_restore_candidates_conn(
            conn, row, group_ids, teacher, cancel_dt,
            orig_wd_idx, orig_slot_idx,
            start_from, 10,
        )

        if not candidates:
            results["no_slots"] += 1
            results["details"].append({
                "lesson_title": row["title"],
                "group_name": "",
                "status": "no_slots",
            })
            continue

        best = candidates[0]

        new_schedule_ids = []
        for scid in sibling_cids:
            sid_info = conn.execute("""
                SELECT s.lesson_id, s.group_id FROM cancellations c
                JOIN schedule s ON c.schedule_id = s.id
                WHERE c.id = ?
            """, (scid,)).fetchone()
            if sid_info is None:
                continue

            start_iso = _to_iso(best.start)
            end_iso = _to_iso(best.end)

            conn.execute("""
                INSERT INTO schedule (lesson_id, group_id, room_id, weekday, start, end, week_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (sid_info["lesson_id"], sid_info["group_id"], best.room_id,
                  best.weekday, start_iso, end_iso, best.week_type))
            new_sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            new_schedule_ids.append(new_sid)

            conn.execute("""
                UPDATE cancellations SET is_restored = 1, restored_schedule_id = ?
                WHERE id = ?
            """, (new_sid, scid))

        conn.commit()

        results["restored"] += 1
        results["details"].append({
            "lesson_title": row["title"],
            "lesson_type": row["lesson_type"],
            "teacher": row["teacher"],
            "group_name": row["group_name"],
            "cancel_date": str(cancel_dt),
            "new_weekday": best.weekday,
            "new_start": best.start,
            "new_end": best.end,
            "new_room": best.room_name,
            "penalty": best.penalty,
            "status": "restored",
        })

    conn.close()
    return results


def _find_sibling_cancellation_ids(conn, lesson_id, weekday, start, week_type,
                                    cancel_date) -> list[int]:
    rows = conn.execute("""
        SELECT c.id FROM cancellations c
        JOIN schedule s ON c.schedule_id = s.id
        WHERE c.cancel_date = ? AND c.is_restored = 0
          AND s.lesson_id = ? AND s.weekday = ? AND s.start = ? AND s.week_type = ?
    """, (cancel_date, lesson_id, weekday, start, week_type)).fetchall()
    return [r["id"] for r in rows]


def delete_cancellation(cid: int):
    conn = _connect()
    row = conn.execute("SELECT is_restored, restored_schedule_id FROM cancellations WHERE id = ?",
                       (cid,)).fetchone()
    if row and row["is_restored"] and row["restored_schedule_id"]:
        conn.execute("DELETE FROM schedule WHERE id = ?", (row["restored_schedule_id"],))
    conn.execute("DELETE FROM cancellations WHERE id = ?", (cid,))
    conn.commit()
    conn.close()


def get_all_teachers() -> list[str]:
    conn = _connect()
    rows = conn.execute("""
        SELECT DISTINCT teacher FROM lessons WHERE teacher IS NOT NULL AND teacher != ''
        ORDER BY teacher
    """).fetchall()
    conn.close()
    return [r["teacher"] for r in rows]


def get_all_disciplines() -> list[str]:
    conn = _connect()
    rows = conn.execute("SELECT DISTINCT title FROM lessons ORDER BY title").fetchall()
    conn.close()
    return [r["title"] for r in rows]
