"""
Единый пайплайн: API schedule.misis.club → SQLite DB

Запуск:
    python pipeline/build_db.py                        # все группы из info.txt
    python pipeline/build_db.py --groups БИВТ-25-1 БИВТ-25-2  # конкретные группы

Результат: data/schedule.db с таблицами rooms, groups, lessons, schedule,
           transfers, event_bookings — полностью готовая к работе БД.
"""

from __future__ import annotations

import re
import json
import random
import sqlite3
import argparse
import sys
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict

import requests
import icalendar

# ──────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "schedule.db"
INFO_FILE = PROJECT_ROOT / "pipeline" / "info.txt"

BASE_MONDAY = date(2026, 1, 12)
API_BASE = "https://schedule.misis.club/api/ical/group"

WEEKDAY_MAP = {0: "Понедельник", 1: "Вторник", 2: "Среда",
               3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}

EXCLUDED_BUILDINGS = {"Онлайн", "Каф. ИЯКТ", "Спортивный комплекс Беляево"}

VALID_LESSON_TYPES = {
    "Лекционные", "Практические", "Лабораторные",
    "Лекция", "Практика", "Лабораторная",
    "лекционные", "практические", "лабораторные",
}

SLOTS = [
    {"name": "1-я пара", "start": "09:00", "end": "10:35"},
    {"name": "2-я пара", "start": "10:50", "end": "12:25"},
    {"name": "3-я пара", "start": "12:40", "end": "14:15"},
    {"name": "4-я пара", "start": "14:30", "end": "16:05"},
    {"name": "5-я пара", "start": "16:20", "end": "17:55"},
    {"name": "6-я пара", "start": "18:00", "end": "19:25"},
    {"name": "7-я пара", "start": "19:35", "end": "21:00"},
]

random.seed(42)


# ──────────────────────────────────────────────
# Шаг 1: Чтение списка групп
# ──────────────────────────────────────────────

def read_groups_from_info(filepath: Path) -> list[str]:
    groups = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    sections = content.split("----------")
    if not sections:
        return groups
    for line in sections[0].split("\n"):
        line = line.strip()
        if not line or line.startswith(("1 курс", "2 курс", "3 курс", "4 курс",
                                         "Магистратура", "Обратите")):
            continue
        for g in line.split(","):
            g = g.strip()
            if g:
                groups.append(g)
    return groups


# ──────────────────────────────────────────────
# Шаг 2: Запрос к API + парсинг iCal
# ──────────────────────────────────────────────

def fetch_group(group_name: str) -> list[dict]:
    url = f"{API_BASE}/{group_name}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  FAIL {group_name}: {e}")
        return []

    cal = icalendar.Calendar.from_ical(r.content)
    lessons = []

    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue

        summary = str(comp.get("SUMMARY", ""))
        location = str(comp.get("LOCATION", ""))
        dtstart = comp.get("DTSTART")
        dtend = comp.get("DTEND")
        rrule = comp.get("RRULE")

        if dtstart is None or dtend is None:
            continue

        start_dt = dtstart.dt if hasattr(dtstart, "dt") else dtstart
        end_dt = dtend.dt if hasattr(dtend, "dt") else dtend

        if not hasattr(start_dt, "hour"):
            start_dt = datetime.combine(start_dt, datetime.min.time())
            end_dt = datetime.combine(end_dt, datetime.min.time())

        weekday = WEEKDAY_MAP.get(start_dt.weekday(), "Unknown")

        week_type = "weekly"
        if rrule:
            interval = rrule.get("INTERVAL", [1])
            try:
                iv = interval[0] if hasattr(interval, "__getitem__") else interval
                if int(iv) == 2:
                    week_type = "alternating"
            except (ValueError, TypeError):
                pass

        title, lesson_type, teacher = parse_summary(summary)

        if location == group_name:
            location = "Онлайн"

        lessons.append({
            "title": title,
            "type": lesson_type,
            "teacher": teacher,
            "location": location if location else "Онлайн",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "weekday": weekday,
            "week_type": week_type,
            "source_name": group_name,
        })

    return lessons


def parse_summary(summary: str) -> tuple[str, str, str]:
    summary = summary.strip()
    teacher = ""
    title = ""
    lesson_type = ""

    m = re.search(r"\[([^\]]+)\]", summary)
    if m:
        teacher = clean_teacher(m.group(1))
        summary = summary[:m.start()].strip()

    for match in reversed(list(re.finditer(r"\(([^)]+)\)", summary))):
        if match.group(1).strip() in VALID_LESSON_TYPES:
            lesson_type = match.group(1).strip()
            summary = summary[:match.start()].strip()
            break

    title = re.sub(r"^\d+(,\s*\d+)*\s*п\.г\.\s*", "", summary)
    title = re.sub(r"^с\s+\d{2}:\d{2}\s+до\s+\d{2}:\d{2}\s+", "", title)
    return title, lesson_type, teacher


def clean_teacher(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"(\w)\s+(\w)(?=\w)", r"\1\2", name).strip()


# ──────────────────────────────────────────────
# Шаг 3: Определение upper/lower недели
# ──────────────────────────────────────────────

def assign_week_type(lessons: list[dict]) -> list[dict]:
    for l in lessons:
        if l["week_type"] == "alternating":
            dt = datetime.fromisoformat(l["start"])
            week_num = (dt.date() - BASE_MONDAY).days // 7 + 1
            l["week_type"] = "upper" if week_num % 2 == 1 else "lower"
        elif l["week_type"] == "weekly":
            dt = datetime.fromisoformat(l["start"])
            week_num = (dt.date() - BASE_MONDAY).days // 7 + 1
            l["week_type"] = "upper" if week_num % 2 == 1 else "lower"
    return lessons


# ──────────────────────────────────────────────
# Шаг 4: Нормализация
# ──────────────────────────────────────────────

def normalize(lessons: list[dict]) -> list[dict]:
    for l in lessons:
        l["start"] = clean_datetime(l["start"])
        l["end"] = clean_datetime(l["end"])

    seen = set()
    cleaned = []
    for l in lessons:
        key = (l["source_name"], l["title"], l["type"], l["teacher"] or "",
               l["weekday"], l["start"], l["end"], l["week_type"], l["location"])
        if key not in seen:
            seen.add(key)
            cleaned.append(l)
    return cleaned


def clean_datetime(dt_str: str) -> str:
    base = dt_str[:19]
    tz = dt_str[19:]
    return base[:17] + "00" + tz


# ──────────────────────────────────────────────
# Шаг 5-6: Создание БД + заполнение
# ──────────────────────────────────────────────

def create_db(lessons: list[dict], db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            students_count INTEGER
        );
        CREATE TABLE rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            building TEXT,
            floor INTEGER,
            capacity INTEGER,
            has_projector BOOLEAN DEFAULT 0,
            has_computers BOOLEAN DEFAULT 0
        );
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            lesson_type TEXT NOT NULL,
            teacher TEXT,
            needs_projector BOOLEAN DEFAULT 0,
            needs_computers BOOLEAN DEFAULT 0
        );
        CREATE TABLE schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            weekday TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            week_type TEXT,
            FOREIGN KEY (lesson_id) REFERENCES lessons(id),
            FOREIGN KEY (group_id) REFERENCES groups(id),
            FOREIGN KEY (room_id) REFERENCES rooms(id)
        );
        CREATE TABLE transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            schedule_id INTEGER,
            old_room_id INTEGER,
            new_room_id INTEGER,
            weekday TEXT,
            start TEXT,
            end TEXT,
            week_type TEXT,
            lesson_id INTEGER,
            group_id INTEGER,
            reason TEXT,
            booking_date TEXT
        );
        CREATE TABLE event_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            room_id INTEGER,
            weekday TEXT,
            start TEXT,
            end TEXT,
            week_type TEXT,
            event_name TEXT,
            organizer TEXT,
            attendees_count INTEGER,
            needs_projector BOOLEAN DEFAULT 0,
            needs_computers BOOLEAN DEFAULT 0,
            booking_date TEXT
        );
        CREATE TABLE cancellations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            cancel_date TEXT NOT NULL,
            reason TEXT,
            is_restored BOOLEAN DEFAULT 0,
            restored_schedule_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES schedule(id)
        );
        CREATE INDEX idx_cancellations_date ON cancellations(cancel_date);
        CREATE INDEX idx_cancellations_schedule ON cancellations(schedule_id);
        CREATE INDEX idx_cancellations_restored ON cancellations(is_restored);
        CREATE TABLE incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE incident_rooms (
            incident_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            FOREIGN KEY (incident_id) REFERENCES incidents(id),
            PRIMARY KEY (incident_id, room_id)
        );
    """)

    groups = set()
    rooms = set()
    lesson_keys = set()

    for item in lessons:
        groups.add(item["source_name"])
        rooms.add(item["location"])
        lesson_keys.add((item["title"], item["type"], item["teacher"] or ""))

    for g in sorted(groups):
        n = random.randint(20, 35) if re.search(r"-(24|25)-", g) else random.randint(15, 30)
        cur.execute("INSERT INTO groups (name, students_count) VALUES (?, ?)", (g, n))

    for r in sorted(rooms):
        building, floor = parse_room_name(r)
        cur.execute("INSERT INTO rooms (name, building, floor) VALUES (?, ?, ?)",
                    (r, building, floor))

    lesson_map = {}
    for title, ltype, teacher in sorted(lesson_keys):
        proj, comp = infer_lesson_equipment(title, ltype)
        cur.execute("INSERT INTO lessons (title, lesson_type, teacher, needs_projector, needs_computers) VALUES (?, ?, ?, ?, ?)",
                    (title, ltype, teacher, proj, comp))
        lesson_map[(title, ltype, teacher)] = cur.lastrowid

    group_map = dict(cur.execute("SELECT name, id FROM groups").fetchall())
    room_map = dict(cur.execute("SELECT name, id FROM rooms").fetchall())

    inserted = 0
    for item in lessons:
        lid = lesson_map.get((item["title"], item["type"], item["teacher"] or ""))
        gid = group_map.get(item["source_name"])
        rid = room_map.get(item["location"])
        if lid and gid and rid:
            cur.execute(
                "INSERT INTO schedule (lesson_id, group_id, room_id, weekday, start, end, week_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (lid, gid, rid, item["weekday"], item["start"], item["end"], item["week_type"]),
            )
            inserted += 1

    conn.commit()

    fill_room_attributes(conn)

    conn.commit()
    conn.close()

    print(f"\nБД создана: {db_path}")
    print(f"  schedule: {inserted} записей")


def parse_room_name(name: str) -> tuple[str, int]:
    parts = name.split("-")
    building = parts[0] if parts else ""
    floor = 0
    if len(parts) > 1:
        try:
            floor_str = parts[1].split("-")[0].split("_")[0]
            digits = "".join(ch for ch in floor_str if ch.isdigit())
            if len(digits) > 2:
                floor = int(digits[:-2])
            elif digits:
                floor = int(digits[0])
        except ValueError:
            floor = 0
    return building, floor


def infer_lesson_equipment(title: str, lesson_type: str) -> tuple[int, int]:
    t = title.lower()
    if "физическ" in t or "спорт" in t or "физическая культура" in t:
        return 0, 0
    if lesson_type == "Лекционные":
        return 1, 0
    if lesson_type == "Лабораторные":
        return 1, 1
    if lesson_type == "Практические":
        return random.choice([1, 1, 0]), random.choice([1, 0, 0, 0])
    return 0, 0


def fill_room_attributes(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    max_per_room = dict(cur.execute("""
        SELECT s.room_id, MAX(g.students_count)
        FROM schedule s JOIN groups g ON s.group_id = g.id
        GROUP BY s.room_id
    """).fetchall())

    equip_per_room = {r[0]: (r[1], r[2]) for r in cur.execute("""
        SELECT s.room_id,
               MAX(l.needs_projector),
               MAX(l.needs_computers)
        FROM schedule s JOIN lessons l ON s.lesson_id = l.id
        GROUP BY s.room_id
    """).fetchall()}

    lecture_flow = defaultdict(int)
    cur.execute("""
        SELECT s.room_id, l.id, SUM(g.students_count)
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        WHERE l.lesson_type = 'Лекционные'
        GROUP BY s.room_id, l.id, s.weekday, s.start, s.end, s.week_type
    """)
    for room_id, _, total in cur.fetchall():
        lecture_flow[room_id] = max(lecture_flow[room_id], total)

    cur.execute("SELECT id, name, building, floor FROM rooms")
    updates = []
    for room_id, name, building, floor in cur.fetchall():
        if building in EXCLUDED_BUILDINGS:
            if building == "Онлайн":
                updates.append((999, 1, 1, room_id))
            elif building == "Спортивный комплекс Беляево":
                updates.append((random.randint(100, 200), 0, 0, room_id))
            elif building == "Каф. ИЯКТ":
                base = max_per_room.get(room_id, 20)
                updates.append((base + random.randint(0, 5), 1, 0, room_id))
            continue

        proj, comp = equip_per_room.get(room_id, (0, 0))

        if room_id in max_per_room:
            base_cap = max(max_per_room[room_id], lecture_flow.get(room_id, 0))
            cap = base_cap + random.randint(0, 10)
        else:
            if building == "Г":
                cap, proj, comp = random.randint(25, 35), 1, 1
            elif building in ("А", "Л"):
                cap, proj, comp = random.randint(30, 60), 1, 0
            else:
                cap, proj, comp = random.randint(20, 40), 0, 0

        updates.append((cap, proj, comp, room_id))

    cur.executemany(
        "UPDATE rooms SET capacity = ?, has_projector = ?, has_computers = ? WHERE id = ?",
        updates,
    )
    print(f"  rooms: обновлено {len(updates)} аудиторий")


# ──────────────────────────────────────────────
# Шаг 7: Верификация
# ──────────────────────────────────────────────

def verify(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    tables = ["groups", "rooms", "lessons", "schedule", "transfers", "event_bookings", "cancellations", "incidents", "incident_rooms"]
    print("\n=== Верификация ===")
    for t in tables:
        cnt = cur.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        print(f"  {t}: {cnt}")

    cap_conflicts = cur.execute("""
        SELECT COUNT(*) FROM schedule s
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE g.students_count > r.capacity AND r.building NOT IN ('Онлайн')
    """).fetchone()[0]

    equip_conflicts = cur.execute("""
        SELECT COUNT(*) FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN rooms r ON s.room_id = r.id
        WHERE (l.needs_projector AND NOT r.has_projector)
           OR (l.needs_computers AND NOT r.has_computers)
    """).fetchone()[0]

    print(f"\n  Конфликты вместимости: {cap_conflicts}")
    print(f"  Конфликты оборудования: {equip_conflicts}")

    if cap_conflicts > 0:
        print("\n  Примеры конфликтов вместимости:")
        for row in cur.execute("""
            SELECT r.name, r.capacity, g.name, g.students_count, l.title
            FROM schedule s
            JOIN groups g ON s.group_id = g.id
            JOIN rooms r ON s.room_id = r.id
            JOIN lessons l ON s.lesson_id = l.id
            WHERE g.students_count > r.capacity AND r.building NOT IN ('Онлайн')
            LIMIT 5
        """).fetchall():
            print(f"    {row[0]} (cap={row[1]}) ← {row[2]} ({row[3]} студ.) {row[4]}")

    conn.close()


# ──────────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="API → SQLite DB")
    parser.add_argument("--groups", nargs="*", help="Список групп (иначе из info.txt)")
    parser.add_argument("--info", type=str, help="Путь к info.txt")
    parser.add_argument("--no-verify", action="store_true", help="Пропустить верификацию")
    parser.add_argument("--save-raw", action="store_true", help="Сохранить промежуточный JSON")
    args = parser.parse_args()

    if args.groups:
        group_list = args.groups
    elif args.info:
        group_list = read_groups_from_info(Path(args.info))
    elif INFO_FILE.exists():
        group_list = read_groups_from_info(INFO_FILE)
    else:
        print(f"Нет списка групп. Укажите --groups или --info.")
        sys.exit(1)

    print(f"Групп: {len(group_list)}")

    # Шаг 2: Запрос к API
    print("\n[1/4] Запрос расписания с API...")
    all_lessons = []
    ok = 0
    for i, g in enumerate(group_list, 1):
        lessons = fetch_group(g)
        if lessons:
            ok += 1
        all_lessons.extend(lessons)
        if i % 10 == 0 or i == len(group_list):
            print(f"  [{i}/{len(group_list)}] {ok} с расписанием, {len(all_lessons)} занятий всего")
    print(f"  Итого: {ok}/{len(group_list)} групп, {len(all_lessons)} занятий")

    if not all_lessons:
        print("Нет данных — выход")
        sys.exit(1)

    # Шаг 3: Определение upper/lower
    print("\n[2/4] Определение типа недели (upper/lower)...")
    all_lessons = assign_week_type(all_lessons)
    wt_counts = defaultdict(int)
    for l in all_lessons:
        wt_counts[l["week_type"]] += 1
    for wt, cnt in sorted(wt_counts.items()):
        print(f"  {wt}: {cnt}")

    # Шаг 4: Нормализация
    print("\n[3/4] Нормализация...")
    before = len(all_lessons)
    all_lessons = normalize(all_lessons)
    print(f"  Удалено дублей: {before - len(all_lessons)}")
    print(f"  Осталось: {len(all_lessons)}")

    if args.save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        out = RAW_DIR / "schedule_clean.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(all_lessons, f, ensure_ascii=False, indent=2)
        print(f"  JSON сохранён: {out}")

    # Шаги 5-6: Создание БД
    print("\n[4/4] Создание БД...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    create_db(all_lessons, DB_PATH)

    # Шаг 7: Верификация
    if not args.no_verify:
        verify(DB_PATH)

    print("\nГотово!")


if __name__ == "__main__":
    main()
