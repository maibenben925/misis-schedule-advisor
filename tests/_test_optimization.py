from optimization import mass_reallocate
from search_engine import get_lesson_info
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.db")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ТЕСТ: Перенос занятий из корпуса Л в разные временные слоты
print("=== ТЕСТ: Массовый перенос корпуса Л (Понедельник, upper, разные слоты) ===\n")

rows = c.execute("""
    SELECT s.id, r.name, r.building, s.weekday, substr(s.start,12,5) as stime,
           substr(s.end,12,5) as etime, s.week_type, l.lesson_type, g.name as group_name
    FROM schedule s
    JOIN rooms r ON s.room_id = r.id
    JOIN lessons l ON s.lesson_id = l.id
    JOIN groups g ON s.group_id = g.id
    WHERE r.building = 'Л' AND s.weekday = 'Понедельник' AND s.week_type = 'upper'
    ORDER BY s.start, s.end
""").fetchall()

sids = [r["id"] for r in rows]
print(f"Занятий для переноса: {len(sids)}")

# Покажем по слотам
slots = {}
for r in rows:
    key = f"{r['stime']}-{r['etime']}"
    slots.setdefault(key, []).append(r)

for slot, items in sorted(slots.items()):
    print(f"\n  Слот {slot} ({len(items)} занятий):")
    for r in items[:5]:
        print(f"    #{r['id']:4d} {r['name']:15s} {r['lesson_type']:15s} {r['group_name']}")
    if len(items) > 5:
        print(f"    ... и ещё {len(items) - 5}")

print(f"\n{'='*80}")
result = mass_reallocate(sids)

print(f"\n--- ИТОГ ---")
print(f"Всего занятий:      {result.n_lessons}")
print(f"Успешно назначено:  {len(result.assignments)}")
print(f"Не хватило мест:    {len(result.unassigned)}")
print(f"Суммарный штраф:    {result.total_penalty}")
print(f"Средний штраф:      {result.avg_penalty}")
print(f"Средний match:      {result.avg_match_percent}%")

# Покажем результат по слотам
print(f"\n--- НАЗНАЧЕНИЯ по слотам ---")
slot_assignments = {}
for sid in sorted(result.assignments.keys()):
    s = result.assignments[sid]
    info = get_lesson_info(sid)
    time_key = f"{info['start'][11:16]}-{info['end'][11:16]}"
    slot_assignments.setdefault(time_key, []).append((sid, s, info))

for slot_time in sorted(slot_assignments.keys()):
    items = slot_assignments[slot_time]
    print(f"\n  Слот {slot_time} ({len(items)} назначений):")
    for sid, s, info in items[:10]:
        tag = ""
        if s.building == info["room_building"]:
            tag = " ← тот же корпус"
        print(f"    {info['room_name']:15s} → {s.name:15s}  penalty={s.penalty:4d}  {s.match_percent:5.1f}%{tag}")
    if len(items) > 10:
        print(f"    ... и ещё {len(items) - 10}")

if result.unassigned:
    print(f"\n--- НЕ ХВАТИЛО МЕСТА ({len(result.unassigned)}) ---")
    unassigned_slots = {}
    for sid in result.unassigned:
        info = get_lesson_info(sid)
        time_key = f"{info['start'][11:16]}-{info['end'][11:16]}"
        unassigned_slots.setdefault(time_key, []).append((sid, info))

    for slot_time in sorted(unassigned_slots.keys()):
        items = unassigned_slots[slot_time]
        print(f"\n  Слот {slot_time} ({len(items)} не назначено):")
        for sid, info in items[:5]:
            print(f"    #{sid}: {info['lesson_title']} | {info['group_name']} | proj={info['needs_projector']} comp={info['needs_computers']}")
        if len(items) > 5:
            print(f"    ... и ещё {len(items) - 5}")

conn.close()
