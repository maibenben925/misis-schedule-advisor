from search_engine import get_lesson_info, get_valid_alternatives, find_room_for_event, get_free_rooms

info = get_lesson_info(2)
print(f"Занятие: {info['lesson_title']}")
print(f"Группа: {info['group_name']} ({info['students_count']} чел.)")
print(f"Время: {info['weekday']} {info['start'][11:16]}-{info['end'][11:16]}")
print(f"Нужно: проектор={bool(info['needs_projector'])}, компьютеры={bool(info['needs_computers'])}")
print(f"Текущая: {info['room_name']}")

alts = get_valid_alternatives(2)
comp_alts = [a for a in alts if a['has_computers']]
print(f"\nВсего свободных в слоте 10:50-12:25: {len(alts)}")
print(f"Из них с компьютерами: {len(comp_alts)}")
for a in comp_alts[:5]:
    print(f"  {a['name']:15s} cap={a['capacity']} proj={a['has_projector']} comp={a['has_computers']}")

# Проверим: пулы свободных аудиторий различаются для 1-й и 2-й пары
free_1 = get_free_rooms("Понедельник", "2026-01-12T09:00:00+03:00", "2026-01-12T10:35:00+03:00", "upper")
free_2 = get_free_rooms("Понедельник", "2026-01-12T10:50:00+03:00", "2026-01-12T12:25:00+03:00", "upper")
print(f"\nСвободных на 1-й паре (09:00): {len(free_1)}")
print(f"Свободных на 2-й паре (10:50): {len(free_2)}")
print(f"Пулы разные? {len(free_1) != len(free_2)}")

# find_room_for_event
print("\n=== find_room_for_event: 25 чел, ПК+проектор, 10:50-12:25 ===")
results = find_room_for_event(
    capacity=25, needs_projector=True, needs_computers=True,
    weekday='Понедельник',
    start='2026-01-12T10:50:00+03:00',
    end='2026-01-12T12:25:00+03:00',
    week_type='upper', top_n=5
)
for r in results:
    print(f"  {r['name']:15s} cap={r['capacity']} proj={r['has_projector']} comp={r['has_computers']}")
