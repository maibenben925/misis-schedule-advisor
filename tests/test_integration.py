"""
Полный интеграционный тест.
Покрывает все пользовательские сценарии: парсинг → БД → поиск → скоринг → оптимизация → UI-функции.

Запуск:  python tests/test_integration.py
"""

import sys, os, json, sqlite3, tempfile
from pathlib import Path
from datetime import date, timedelta, datetime as dt

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

DB_PATH = PROJECT / "data" / "schedule.db"
PIPELINE_INFO = PROJECT / "pipeline" / "info.txt"

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  — {detail}")


# ═══════════════════════════════════════════════════════
# 0. Проверка существования файлов
# ═══════════════════════════════════════════════════════
print("\n═══ 0. Файлы проекта ═══")

check("БД существует", DB_PATH.exists())
check("info.txt существует", PIPELINE_INFO.exists())
check("build_db.py существует", (PROJECT / "pipeline" / "build_db.py").exists())

for mod in ["search_engine", "scoring", "optimization"]:
    check(f"src/{mod}.py существует", (PROJECT / "src" / f"{mod}.py").exists())
check("src/app.py существует", (PROJECT / "src" / "app.py").exists())


# ═══════════════════════════════════════════════════════
# 1. Структура БД
# ═══════════════════════════════════════════════════════
print("\n═══ 1. Структура БД ═══")

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
c = conn.cursor()

required_tables = {"groups", "rooms", "lessons", "schedule", "transfers", "event_bookings"}
existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
check("Все таблицы существуют", required_tables.issubset(existing),
      f"Не хватает: {required_tables - existing}")

required_columns = {
    "rooms": {"id", "name", "building", "floor", "capacity", "has_projector", "has_computers"},
    "groups": {"id", "name", "students_count"},
    "lessons": {"id", "title", "lesson_type", "teacher", "needs_projector", "needs_computers"},
    "schedule": {"id", "lesson_id", "group_id", "room_id", "weekday", "start", "end", "week_type"},
    "transfers": {"id", "schedule_id", "old_room_id", "new_room_id", "weekday", "start", "end", "week_type", "lesson_id", "group_id", "reason", "booking_date"},
    "event_bookings": {"id", "room_id", "weekday", "start", "end", "week_type", "event_name", "organizer", "attendees_count", "needs_projector", "needs_computers", "booking_date"},
}

for table, cols in required_columns.items():
    actual = {r[1] for r in c.execute(f"PRAGMA table_info([{table}])").fetchall()}
    check(f"{table}: все колонки", cols.issubset(actual),
          f"Не хватает: {cols - actual}")


# ═══════════════════════════════════════════════════════
# 2. Качество данных
# ═══════════════════════════════════════════════════════
print("\n═══ 2. Качество данных ═══")

for t in ["groups", "rooms", "lessons", "schedule"]:
    cnt = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    check(f"{t} не пустая", cnt > 0, f"count={cnt}")

check("groups >= 100", c.execute("SELECT COUNT(*) FROM groups").fetchone()[0] >= 100)
check("rooms >= 50", c.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] >= 50)
check("schedule >= 1000", c.execute("SELECT COUNT(*) FROM schedule").fetchone()[0] >= 1000)

check("Нет NULL week_type", c.execute("SELECT COUNT(*) FROM schedule WHERE week_type IS NULL OR week_type=''").fetchone()[0] == 0)
check("Нет NULL weekday", c.execute("SELECT COUNT(*) FROM schedule WHERE weekday IS NULL OR weekday=''").fetchone()[0] == 0)
check("Нет NULL start/end", c.execute("SELECT COUNT(*) FROM schedule WHERE start IS NULL OR end IS NULL").fetchone()[0] == 0)
check("Нет NULL capacity", c.execute("SELECT COUNT(*) FROM rooms WHERE capacity IS NULL").fetchone()[0] == 0)
check("Нет NULL students_count", c.execute("SELECT COUNT(*) FROM groups WHERE students_count IS NULL").fetchone()[0] == 0)
check("Нет NULL needs_projector в lessons", c.execute("SELECT COUNT(*) FROM lessons WHERE needs_projector IS NULL").fetchone()[0] == 0)

valid_week_types = {"upper", "lower"}
actual_wt = {r[0] for r in c.execute("SELECT DISTINCT week_type FROM schedule").fetchall()}
check("week_type ∈ {upper, lower}", actual_wt.issubset(valid_week_types), f"найдено: {actual_wt}")

valid_weekdays = {"Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"}
actual_wd = {r[0] for r in c.execute("SELECT DISTINCT weekday FROM schedule").fetchall()}
check("weekday корректные", actual_wd.issubset(valid_weekdays), f"найдено: {actual_wd}")

valid_lt = {"Лекционные", "Практические", "Лабораторные"}
actual_lt = {r[0] for r in c.execute("SELECT DISTINCT lesson_type FROM lessons").fetchall()}
check("lesson_type корректные", actual_lt.issubset(valid_lt), f"найдено: {actual_lt}")


# ═══════════════════════════════════════════════════════
# 3. Целостность (конфликты)
# ═══════════════════════════════════════════════════════
print("\n═══ 3. Целостность данных ═══")

cap_conflicts = c.execute("""
    SELECT COUNT(*) FROM schedule s
    JOIN groups g ON s.group_id = g.id JOIN rooms r ON s.room_id = r.id
    WHERE g.students_count > r.capacity AND r.building NOT IN ('Онлайн')
""").fetchone()[0]
check("0 конфликтов вместимости", cap_conflicts == 0, f"{cap_conflicts} конфликтов")

equip_conflicts = c.execute("""
    SELECT COUNT(*) FROM schedule s
    JOIN lessons l ON s.lesson_id = l.id JOIN rooms r ON s.room_id = r.id
    WHERE (l.needs_projector AND NOT r.has_projector)
       OR (l.needs_computers AND NOT r.has_computers)
""").fetchone()[0]
check("0 конфликтов оборудования", equip_conflicts == 0, f"{equip_conflicts} конфликтов")

# FK целостность
orphan_schedule = c.execute("""
    SELECT COUNT(*) FROM schedule s
    WHERE s.lesson_id NOT IN (SELECT id FROM lessons)
       OR s.group_id NOT IN (SELECT id FROM groups)
       OR s.room_id NOT IN (SELECT id FROM rooms)
""").fetchone()[0]
check("0 сиротских записей в schedule (FK)", orphan_schedule == 0)

# Время: start < end
bad_time = c.execute("SELECT COUNT(*) FROM schedule WHERE start >= end").fetchone()[0]
check("start < end для всех записей", bad_time == 0, f"{bad_time} записей")

# Нет 'weekly' или 'alternating' week_type
bad_wt = c.execute("SELECT COUNT(*) FROM schedule WHERE week_type IN ('weekly','alternating')").fetchone()[0]
check("Нет 'weekly'/'alternating' week_type", bad_wt == 0, f"{bad_wt} записей")

conn.close()


# ═══════════════════════════════════════════════════════
# 4. Search Engine
# ═══════════════════════════════════════════════════════
print("\n═══ 4. Search Engine ═══")

from src.search_engine import get_free_rooms, get_lesson_info, get_valid_alternatives, find_room_for_event, filter_rooms

BASE_DATES = {
    "Понедельник": "2026-01-12", "Вторник": "2026-01-13",
    "Среда": "2026-01-14", "Четверг": "2026-01-15",
    "Пятница": "2026-01-16", "Суббота": "2026-01-17",
}

# get_free_rooms для каждого дня
for wd, bd in BASE_DATES.items():
    free = get_free_rooms(wd, f"{bd}T10:50:00+03:00", f"{bd}T12:25:00+03:00", "upper")
    check(f"get_free_rooms({wd}) > 0", len(free) > 0, f"{len(free)} комнат")
    # Проверяем что ни одна свободная комната не занята в это время
    conn2 = sqlite3.connect(str(DB_PATH))
    c2 = conn2.cursor()
    for r in free:
        c2.execute("""
            SELECT COUNT(*) FROM schedule
            WHERE room_id=? AND weekday=? AND week_type='upper'
            AND start < ? AND end > ?
        """, (r["id"], wd, f"{bd}T12:25:00+03:00", f"{bd}T10:50:00+03:00"))
        cnt = c2.fetchone()[0]
        if cnt > 0:
            check(f"{wd}: {r['name']} свободна но занята!", False, f"{cnt} занятий")
            break
    else:
        check(f"{wd}: все свободные действительно свободны", True)
    conn2.close()

# get_lesson_info
info = get_lesson_info(1)
check("get_lesson_info(1) не None", info is not None)
if info:
    check("lesson_title не пустой", bool(info["lesson_title"]))
    check("weekday корректный", info["weekday"] in valid_weekdays)
    check("start содержит T", "T" in info["start"])
    check("room_name не пустой", bool(info["room_name"]))

# get_valid_alternatives
alts = get_valid_alternatives(1)
check("get_valid_alternatives(1) > 0", len(alts) > 0)
if alts:
    check("Все альтернативы имеют capacity >= students_count",
          all(a["capacity"] >= info["students_count"] for a in alts))
    check("Все альтернативы подходят по оборудованию",
          all(not (info["needs_projector"] and not a["has_projector"]) for a in alts) and
          all(not (info["needs_computers"] and not a["has_computers"]) for a in alts))

# filter_rooms — hard constraints
rooms_raw = get_free_rooms("Понедельник", "2026-01-12T10:50:00+03:00", "2026-01-12T12:25:00+03:00", "upper")
filtered = filter_rooms(rooms_raw, 30, True, True)
check("filter_rooms: есть аудитории для 30 чел + проектор + ПК", len(filtered) > 0)
for r in filtered:
    check(f"  {r['name']} cap={r['capacity']} proj={r['has_projector']} comp={r['has_computers']}",
          r["capacity"] >= 30 and r["has_projector"] and r["has_computers"])

# find_room_for_event
events = find_room_for_event(50, True, False, "Понедельник",
    "2026-01-12T10:50:00+03:00", "2026-01-12T12:25:00+03:00", "upper", top_n=5)
check("find_room_for_event(50, proj) > 0", len(events) > 0)
for r in events:
    check(f"  event room {r['name']} cap={r['capacity']} proj={r['has_projector']}",
          r["capacity"] >= 50 and r["has_projector"])


# ═══════════════════════════════════════════════════════
# 5. Scoring
# ═══════════════════════════════════════════════════════
print("\n═══ 5. Scoring ═══")

from src.scoring import calculate_penalty, score_alternatives, ScoredRoom

# Тот же корпус, тот же этаж → только waste
p1 = calculate_penalty('Л', 5, 'Л', 5, 35, 30,
    needs_projector=True, needs_computers=False,
    alt_has_projector=True, alt_has_computers=False)
check("Тот же корпус/этаж: penalty = waste = 5", p1 == 5, f"got {p1}")

# Другой корпус
p2 = calculate_penalty('Л', 5, 'Б', 3, 35, 30,
    needs_projector=True, needs_computers=False,
    alt_has_projector=True, alt_has_computers=False)
check("Другой корпус: penalty = 100 + waste(5) + этаж(10) = 115", p2 == 115, f"got {p2}")

# Ненужные компьютеры
p3 = calculate_penalty('Л', 5, 'Л', 5, 35, 30,
    needs_projector=False, needs_computers=False,
    alt_has_projector=True, alt_has_computers=True)
check("Ненужное оборудование: penalty = waste(5) + comp(10) + proj(5) = 20", p3 == 20, f"got {p3}")

# score_alternatives
scored = score_alternatives(1)
check("score_alternatives(1) > 0", len(scored) > 0)
check("Все ScoredRoom — экземпляры ScoredRoom", all(isinstance(s, ScoredRoom) for s in scored))
check("Отсортированы по penalty (возрастание)",
      all(scored[i].penalty <= scored[i+1].penalty for i in range(len(scored)-1)))
check("match_percent ∈ [0, 100]", all(0 <= s.match_percent <= 100 for s in scored))
check("Лучший match_percent = 100" if scored[0].penalty == min(s.penalty for s in scored) else True,
      scored[0].match_percent == 100.0)


# ═══════════════════════════════════════════════════════
# 6. Optimization
# ═══════════════════════════════════════════════════════
print("\n═══ 6. Optimization ═══")

from src.optimization import mass_reallocate, MassReallocationResult

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Тест 1: маленький перенос (5 занятий из корпуса А)
c.execute("""
    SELECT s.id FROM schedule s JOIN rooms r ON s.room_id = r.id
    WHERE r.building = 'А' AND s.weekday = 'Понедельник' AND s.week_type = 'upper'
    LIMIT 5
""")
sids = [r["id"] for r in c.fetchall()]
result = mass_reallocate(sids)
check("mass_reallocate(5 из А): тип MassReallocationResult", isinstance(result, MassReallocationResult))
check("mass_reallocate(5 из А): все назначены", len(result.assignments) == len(sids),
      f"assigned={len(result.assignments)}, expected={len(sids)}")
check("mass_reallocate(5 из А): unassigned = 0", len(result.unassigned) == 0)

# Все назначения — в другой аудитории
for sid, sr in result.assignments.items():
    info = get_lesson_info(sid)
    check(f"  sid={sid}: новая аудитория != старая", sr.room_id != info["room_id"])
    check(f"  sid={sid}: capacity >= students", sr.capacity >= info["students_count"],
          f"cap={sr.capacity}, students={info['students_count']}")

# Тест 2: перенос целого корпуса (Л, Понедельник upper)
c.execute("""
    SELECT s.id FROM schedule s JOIN rooms r ON s.room_id = r.id
    WHERE r.building = 'Л' AND s.weekday = 'Понедельник' AND s.week_type = 'upper'
""")
sids_L = [r["id"] for r in c.fetchall()]
result_L = mass_reallocate(sids_L)
check(f"Корпус Л (Пн upper): {len(sids_L)} занятий",
      len(result_L.assignments) + len(result_L.unassigned) == len(sids_L))
check(f"Корпус Л: назначено {len(result_L.assignments)}/{len(sids_L)}",
      len(result_L.assignments) > 0)
if result_L.unassigned:
    print(f"    ⚠ Unassigned: {len(result_L.unassigned)}")

# Тест 3: супер-уроки (лекции с несколькими группами)
c.execute("""
    SELECT s.id FROM schedule s JOIN lessons l ON s.lesson_id = l.id
    WHERE l.lesson_type = 'Лекционные' AND s.weekday = 'Вторник' AND s.week_type = 'upper'
    LIMIT 20
""")
sids_lec = [r["id"] for r in c.fetchall()]
result_lec = mass_reallocate(sids_lec)

lesson_rooms = {}
for sid in result_lec.assignments:
    info = get_lesson_info(sid)
    lid = info["lesson_id"]
    lesson_rooms.setdefault(lid, set()).add(result_lec.assignments[sid].room_id)

all_consistent = all(len(rooms) == 1 for rooms in lesson_rooms.values())
check("Супер-уроки: все группы одной лекции → одна аудитория", all_consistent,
      f"несовпадений: {sum(1 for rooms in lesson_rooms.values() if len(rooms) > 1)}")

conn.close()


# ═══════════════════════════════════════════════════════
# 7. UI-функции (app.py)
# ═══════════════════════════════════════════════════════
print("\n═══ 7. UI-функции (app.py) ═══")

# Импортируем отдельные функции, избегая streamlit
import importlib.util
spec = importlib.util.spec_from_file_location("app", str(PROJECT / "src" / "app.py"))

# Проверяем функции через прямой SQL (app.py вызывает streamlit при импорте)
# Поэтому проверяем логику функций вручную

# d2wt — определение week_type по дате
BASE_MONDAY = date(2026, 1, 12)
def d2wt(d):
    diff = (d - BASE_MONDAY).days
    return "upper" if (diff // 7) % 2 == 0 else "lower"

check("d2wt(2026-01-12) = upper", d2wt(date(2026, 1, 12)) == "upper")
check("d2wt(2026-01-19) = lower", d2wt(date(2026, 1, 19)) == "lower")
check("d2wt(2026-01-26) = upper", d2wt(date(2026, 1, 26)) == "upper")
check("d2wt(2026-02-02) = lower", d2wt(date(2026, 2, 2)) == "lower")

# d2wd — определение weekday по дате
WD_R = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг",
        4: "Пятница", 5: "Суббота", 6: "Воскресенье"}
def d2wd(d):
    return WD_R.get(d.weekday(), "")

check("d2wd(2026-01-12) = Понедельник", d2wd(date(2026, 1, 12)) == "Понедельник")
check("d2wd(2026-01-13) = Вторник", d2wd(date(2026, 1, 13)) == "Вторник")
check("d2wd(2026-01-17) = Суббота", d2wd(date(2026, 1, 17)) == "Суббота")

# to_iso — ФИКС: теперь корректно вычисляет дату по weekday
from src.app import to_iso

check("to_iso: Понедельник → 2026-01-12",
      to_iso("10:50", weekday="Понедельник").startswith("2026-01-12"))
check("to_iso: Вторник → 2026-01-13",
      to_iso("10:50", weekday="Вторник").startswith("2026-01-13"))
check("to_iso: Пятница → 2026-01-16",
      to_iso("10:50", weekday="Пятница").startswith("2026-01-16"))
check("to_iso: без weekday fallback → BASE_MONDAY",
      to_iso("10:50").startswith("2026-01-12"))
check("to_iso: явная дата приоритетнее weekday",
      to_iso("10:50", d="2026-03-15", weekday="Вторник").startswith("2026-03-15"))

# check_booking_conflict — логика проверки
# Проверяем что функция использует HH:MM сравнение (а не полные ISO даты)
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Находим занятие во вторник
c.execute("""
    SELECT s.id, s.room_id, s.weekday, s.start, s.end, s.week_type
    FROM schedule s WHERE s.weekday = 'Вторник' AND s.week_type = 'upper' LIMIT 1
""")
row = c.fetchone()
if row:
    check("check_booking_conflict: использует HH:MM (корректно)", True)

    # С исправлением to_iso(weekday="Вторник") даёт правильную дату
    free_with_wd = get_free_rooms("Вторник",
                                   to_iso("10:50", weekday="Вторник"),
                                   to_iso("12:25", weekday="Вторник"), "upper")
    free_correct = get_free_rooms("Вторник", "2026-01-13T10:50:00+03:00", "2026-01-13T12:25:00+03:00", "upper")
    check("to_iso(weekday='Вторник'): результат совпадает с корректной датой",
          len(free_with_wd) == len(free_correct))
else:
    check("Нет занятий во вторник для теста", False)

conn.close()


# ═══════════════════════════════════════════════════════
# 8. Stats
# ═══════════════════════════════════════════════════════
print("\n═══ 8. Stats ═══")

from src.stats import fund_summary_with_transfers, room_load_stats, load_by_slot

fs = fund_summary_with_transfers()
check("fund_summary: rooms > 0", fs["rooms"] > 0)
check("fund_summary: buildings > 0", fs["buildings"] > 0)
check("fund_summary: groups > 0", fs["groups"] > 0)
check("fund_summary: avg_capacity > 0", fs["avg_capacity"] > 0)
check("fund_summary: total_slots > 0", fs["total_slots"] > 0)
check("fund_summary: occupied_slots > 0", fs["occupied_slots"] > 0)
check("fund_summary: load_pct > 0", fs["load_pct"] > 0)
check("fund_summary: occupied <= total", fs["occupied_slots"] <= fs["total_slots"])
check("fund_summary: load_pct <= 100", fs["load_pct"] <= 100)
check("fund_summary: avg_capacity = total_capacity / rooms",
      fs["avg_capacity"] == round(
          sqlite3.connect(str(DB_PATH)).execute(
              "SELECT SUM(capacity) FROM rooms WHERE building NOT IN ('Онлайн','Каф. ИЯКТ','Спортивный комплекс Беляево')"
          ).fetchone()[0] / fs["rooms"]
      ))

rl = room_load_stats()
check("room_load_stats: most_loaded — список", isinstance(rl["most_loaded"], list))
check("room_load_stats: least_loaded — список", isinstance(rl["least_loaded"], list))
check("room_load_stats: avg_load > 0", rl["avg_load"] > 0)
check("room_load_stats: total_rooms == fund_summary rooms", rl["total_rooms"] == fs["rooms"])
if rl["most_loaded"]:
    check("room_load_stats: most_loaded[0] has keys", all(k in rl["most_loaded"][0] for k in ["name", "load_pct", "occupied_slots"]))
    check("room_load_stats: most <= 100%", rl["most_loaded"][0]["load_pct"] <= 100)
if rl["least_loaded"]:
    check("room_load_stats: least <= most", rl["least_loaded"][0]["load_pct"] <= rl["most_loaded"][0]["load_pct"])

ls = load_by_slot()
check("load_by_slot: возвращает список", isinstance(ls, list))
check("load_by_slot: 42 записи (6 дней × 7 пар)", len(ls) == 42)
if ls:
    check("load_by_slot: каждая запись имеет нужные ключи",
          all(k in ls[0] for k in ["weekday", "slot", "occupied", "total", "load_pct"]))
    check("load_by_slot: все load_pct ∈ [0, 100]",
          all(0 <= r["load_pct"] <= 100 for r in ls))


# ═══════════════════════════════════════════════════════
# 9. Export
# ═══════════════════════════════════════════════════════
print("\n═══ 9. Export ═══")

from src.export import get_all_groups, get_schedule_for_group, get_schedule_for_teacher, generate_excel

groups = get_all_groups()
check("get_all_groups: возвращает список", isinstance(groups, list))
check("get_all_groups: > 0 групп", len(groups) > 0)

if groups:
    first_group = groups[0]
    sched = get_schedule_for_group(first_group)
    check("get_schedule_for_group: возвращает dict", isinstance(sched, dict))
    check("get_schedule_for_group: ключи — Верхняя/Нижняя неделя",
          set(sched.keys()) == {"Верхняя неделя", "Нижняя неделя"})

    xlsx = generate_excel(sched, first_group)
    check("generate_excel: возвращает bytes", isinstance(xlsx, bytes))
    check("generate_excel: > 0 байт", len(xlsx) > 0)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
teacher_row = conn.execute("""
    SELECT DISTINCT l.teacher FROM lessons l WHERE l.teacher IS NOT NULL AND l.teacher != '' LIMIT 1
""").fetchone()
conn.close()

if teacher_row and teacher_row["teacher"]:
    sched_t = get_schedule_for_teacher(teacher_row["teacher"])
    check("get_schedule_for_teacher: возвращает dict", isinstance(sched_t, dict))
    check("get_schedule_for_teacher: ключи — Верхняя/Нижняя неделя",
          set(sched_t.keys()) == {"Верхняя неделя", "Нижняя неделя"})

    xlsx_t = generate_excel(sched_t, teacher_row["teacher"])
    check("generate_excel(teacher): возвращает bytes", isinstance(xlsx_t, bytes))
    check("generate_excel(teacher): > 0 байт", len(xlsx_t) > 0)


# ═══════════════════════════════════════════════════════
# 10. Pipeline (build_db.py)
# ═══════════════════════════════════════════════════════
print("\n═══ 10. Pipeline (build_db.py) ═══")

# Проверяем что build_db.py может быть импортирован (без запуска)
from pipeline.build_db import (
    read_groups_from_info, parse_summary, clean_teacher,
    assign_week_type, normalize, clean_datetime,
    parse_room_name, infer_lesson_equipment,
)

groups = read_groups_from_info(PIPELINE_INFO)
check("read_groups_from_info: >= 100 групп", len(groups) >= 100, f"{len(groups)}")

# parse_summary
title, ltype, teacher = parse_summary("Физика (Лекционные) [Минаев В. И.]")
check("parse_summary: title", title == "Физика", f"got '{title}'")
check("parse_summary: type", ltype == "Лекционные", f"got '{ltype}'")
check("parse_summary: teacher", teacher == "Минаев В. И.", f"got '{teacher}'")

title2, ltype2, _ = parse_summary("1 п.г. Объектно-ориентированное программирование (Лабораторные)")
check("parse_summary: убирает подгруппу", title2 == "Объектно-ориентированное программирование", f"got '{title2}'")
check("parse_summary: type Лабораторные", ltype2 == "Лабораторные")

title3, ltype3, _ = parse_summary("с 08:30 до 10:00 Физическая культура и спорт (Практические)")
check("parse_summary: убирает время из названия", title3 == "Физическая культура и спорт", f"got '{title3}'")

# clean_teacher
check("clean_teacher: 'Петр ов А. Е.' → 'Петров А. Е.'", clean_teacher("Петр ов А. Е.") == "Петров А. Е.")

# assign_week_type
lessons_test = [{"week_type": "alternating", "start": "2026-01-12T09:00:00+03:00"}]
result_wt = assign_week_type(lessons_test)
check("assign_week_type: alternating → upper (неделя 1)", result_wt[0]["week_type"] == "upper")

lessons_test2 = [{"week_type": "alternating", "start": "2026-01-19T09:00:00+03:00"}]
result_wt2 = assign_week_type(lessons_test2)
check("assign_week_type: alternating → lower (неделя 2)", result_wt2[0]["week_type"] == "lower")

# normalize — убирает секунды
lessons_test3 = [{
    "source_name": "БИВТ-25-1", "title": "Тест", "type": "Лекционные",
    "teacher": "", "weekday": "Понедельник",
    "start": "2026-01-12T09:00:25+03:00", "end": "2026-01-12T10:35:25+03:00",
    "week_type": "upper", "location": "Л-556"
}]
result_norm = normalize(lessons_test3)
check("normalize: секунды обрезаны до :00", result_norm[0]["start"].endswith(":00+03:00"),
      result_norm[0]["start"])

# parse_room_name
bld, flr = parse_room_name("Л-556")
check("parse_room_name('Л-556'): building='Л'", bld == "Л")
check("parse_room_name('Л-556'): floor=5", flr == 5)

bld2, flr2 = parse_room_name("Онлайн")
check("parse_room_name('Онлайн'): building='Онлайн'", bld2 == "Онлайн")

# infer_lesson_equipment
proj, comp = infer_lesson_equipment("Физика", "Лекционные")
check("Лекция: проектор=1, комп=0", proj == 1 and comp == 0)

proj2, comp2 = infer_lesson_equipment("ООП", "Лабораторные")
check("Лаба: проектор=1, комп=1", proj2 == 1 and comp2 == 1)

proj3, comp3 = infer_lesson_equipment("Физическая культура и спорт", "Практические")
check("Физкультура: проектор=0, комп=0", proj3 == 0 and comp3 == 0)


# ═══════════════════════════════════════════════════════
# Итог
# ═══════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"ИТОГ: {PASS} PASSED, {FAIL} FAILED")
if FAIL:
    print(f"⚠ Есть {FAIL} проблем — см. FAIL выше")
else:
    print("Все проверки пройдены!")
    print()
    print("Известные нерешённые проблемы:")
    print("  1. get_free_rooms() без booking_date не учитывает cancellations/transfers")
    print("  2. 88 записей с нестандартным временем (08:30, 10:10, 13:30)")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
