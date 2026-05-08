from scoring import score_alternatives
from search_engine import get_lesson_info

# Занятие в корпусе Л — обычный корпус, не спец. случай
info = get_lesson_info(2)
print(f"Занятие: {info['lesson_title']} ({info['lesson_type']})")
print(f"Группа: {info['group_name']} ({info['students_count']} чел.)")
print(f"Текущая: {info['room_name']} (корп.{info['room_building']}, эт.{info['room_floor']})")
print()

scored = score_alternatives(2)
print(f"Всего альтернатив: {len(scored)}")

# Исключаем Онлайн из вывода для наглядности
scored_real = [s for s in scored if s.building != "Онлайн"]

print(f"Реальных аудиторий (без Онлайн): {len(scored_real)}")
print()

print("--- ЛУЧШИЕ 10 ---")
for i, s in enumerate(scored_real[:10], 1):
    tag = ""
    if s.building == info["room_building"] and s.floor == info["room_floor"]:
        tag = " ← тот же корпус и этаж"
    elif s.building == info["room_building"]:
        tag = " ← тот же корпус"
    print(f"  {i:2d}. {s.name:15s} {s.building:5s} эт.{s.floor} cap={s.capacity:3d}  penalty={s.penalty:4d}  {s.match_percent:5.1f}%{tag}")

print(f"\n--- СРЕДНИЕ (позиции 30-35) ---")
for s in scored_real[29:35]:
    print(f"  {s.name:15s} {s.building:5s} эт.{s.floor} cap={s.capacity:3d}  penalty={s.penalty:4d}  {s.match_percent:5.1f}%")

print(f"\n--- ХУДШИЕ 5 (реальные) ---")
for s in scored_real[-5:]:
    print(f"  {s.name:15s} {s.building:5s} эт.{s.floor} cap={s.capacity:3d}  penalty={s.penalty:4d}  {s.match_percent:5.1f}%")

# Отдельно покажем Онлайн
print(f"\n--- Онлайн ---")
online = [s for s in scored if s.building == "Онлайн"]
for s in online:
    print(f"  {s.name:15s} {s.building:5s} эт.{s.floor} cap={s.capacity:3d}  penalty={s.penalty:4d}  {s.match_percent:5.1f}%")
