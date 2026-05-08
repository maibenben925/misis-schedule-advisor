"""Создание SQLite БД из распарсенного расписания."""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "schedule.db"
DATA_DIR = Path(__file__).parent.parent / "data" / "processed"

def create_tables(cursor: sqlite3.Cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            building TEXT,
            floor INTEGER
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            lesson_type TEXT NOT NULL,
            teacher TEXT
        );

        CREATE TABLE IF NOT EXISTS schedule (
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
    """)

def main():
    if DB_PATH.exists():
        print(f"⚠️ Файл {DB_PATH} уже существует. Удаляю старый.")
        DB_PATH.unlink()

    with open(DATA_DIR / "schedule_clean.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    create_tables(cursor)

    groups = set()
    rooms = set()
    lessons = set()

    for item in data:
        groups.add(item["source_name"])
        rooms.add(item["location"])
        key = (item["title"], item["type"], item["teacher"] or "")
        lessons.add(key)

    print(f"Вставляю: {len(groups)} групп, {len(rooms)} аудиторий, {len(lessons)} занятий")

    for g in sorted(groups):
        cursor.execute("INSERT INTO groups (name) VALUES (?)", (g,))

    for r in sorted(rooms):
        parts = r.split("-")
        building = parts[0] if parts else ""
        floor = 0
        if len(parts) > 1:
            try:
                floor_str = parts[1].split("-")[0].split("_")[0]
                for ch in floor_str:
                    if ch.isdigit():
                        floor = int(ch)
                        break
            except ValueError:
                floor = 0
        cursor.execute("INSERT INTO rooms (name, building, floor) VALUES (?, ?, ?)",
                      (r, building, floor))

    lesson_map = {}
    for title, ltype, teacher in sorted(lessons):
        cursor.execute("INSERT INTO lessons (title, lesson_type, teacher) VALUES (?, ?, ?)",
                      (title, ltype, teacher))
        lesson_map[(title, ltype, teacher)] = cursor.lastrowid

    group_map = {}
    cursor.execute("SELECT id, name FROM groups")
    for gid, name in cursor.fetchall():
        group_map[name] = gid

    room_map = {}
    cursor.execute("SELECT id, name FROM rooms")
    for rid, name in cursor.fetchall():
        room_map[name] = rid

    inserted = 0
    for item in data:
        lid = lesson_map.get((item["title"], item["type"], item["teacher"] or ""))
        gid = group_map.get(item["source_name"])
        rid = room_map.get(item["location"])

        if lid and gid and rid:
            cursor.execute(
                """INSERT INTO schedule 
                   (lesson_id, group_id, room_id, weekday, start, end, week_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lid, gid, rid, item["weekday"], item["start"], item["end"],
                 item["week_type"])
            )
            inserted += 1

    conn.commit()

    print(f"\n✅ БД создана: {DB_PATH}")
    print(f"   Занесено: {inserted} записей в schedule")

    cursor.execute("SELECT COUNT(*) FROM groups")
    print(f"   Групп: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM rooms")
    print(f"   Аудиторий: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM lessons")
    print(f"   Уникальных занятий: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM schedule")
    print(f"   Расписание: {cursor.fetchone()[0]}")

    conn.close()

if __name__ == "__main__":
    main()
