"""Тест find_room_for_event."""
from search_engine import find_room_for_event

# Сценарий 1: Конференция на 50 человек с проектором, понедельник, 10:50-12:25
print("=== Конференция: 50 чел, проектор, Пн 10:50-12:25 ===")
results = find_room_for_event(
    capacity=50,
    needs_projector=True,
    needs_computers=False,
    weekday="Понедельник",
    start="2026-01-12T10:50:00+03:00",
    end="2026-01-12T12:25:00+03:00",
    week_type="upper",
    top_n=5,
)
for i, r in enumerate(results, 1):
    waste = r["capacity"] - 50
    print(f"  {i}. {r['name']:15s} cap={r['capacity']} proj={r['has_projector']} comp={r['has_computers']} | избыток={waste}")

# Сценарий 2: Воркшоп с ПК, 30 человек
print("\n=== Воркшоп: 30 чел, ПК+проектор, Среда 14:30-16:05 ===")
results = find_room_for_event(
    capacity=30,
    needs_projector=True,
    needs_computers=True,
    weekday="Среда",
    start="2026-01-14T14:30:00+03:00",
    end="2026-01-14T16:05:00+03:00",
    week_type="lower",
    top_n=5,
)
for i, r in enumerate(results, 1):
    waste = r["capacity"] - 30
    print(f"  {i}. {r['name']:15s} cap={r['capacity']} proj={r['has_projector']} comp={r['has_computers']} | избыток={waste}")

# Сценарий 3: Большой хакатон, 100 человек, нужны ПК
print("\n=== Хакатон: 100 чел, ПК+проектор, Пятница 09:00-12:25 ===")
results = find_room_for_event(
    capacity=100,
    needs_projector=True,
    needs_computers=True,
    weekday="Пятница",
    start="2026-01-16T09:00:00+03:00",
    end="2026-01-16T12:25:00+03:00",
    week_type="upper",
    top_n=5,
)
for i, r in enumerate(results, 1):
    waste = r["capacity"] - 100
    print(f"  {i}. {r['name']:15s} cap={r['capacity']} proj={r['has_projector']} comp={r['has_computers']} | избыток={waste}")
if not results:
    print("  (не нашлось — ожидаемо, комп. классы маленькие)")
