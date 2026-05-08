import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import (
    ensure_tables, get_conn, get_affected_lessons, to_iso,
    save_transfers_to_db, get_transfers, save_event_booking_to_db,
    get_event_bookings, get_schedule_grid, get_transfers_for_slot,
    get_bookings_for_slot
)

# Убедиться что таблицы есть
ensure_tables()

# Проверка affected
room_ids = [1, 2]  # А-304, А-308
slot_keys = [("Понедельник", to_iso("10:50"), to_iso("12:25"), "upper")]
affected = get_affected_lessons(room_ids, slot_keys)
print(f"Affected lessons: {len(affected)}")
for a in affected[:3]:
    print(f"  #{a['id']} {a['lesson_title']} | {a['room_name']} | {a['group_name']}")

# Проверка сохранения переноса
from optimization import mass_reallocate
if affected:
    sids = [a["id"] for a in affected]
    result = mass_reallocate(sids)
    print(f"\nResult: {len(result.assignments)} assigned, {len(result.unassigned)} unassigned")
    save_transfers_to_db(result.assignments)
    tr = get_transfers()
    print(f"Transfers in DB: {len(tr)}")

# Проверка сохранения бронирования
room = {"id": 10, "name": "test"}
save_event_booking_to_db(
    room=room, event_name="Test", organizer="Org", attendees=20,
    weekday="Понедельник", start="10:50", end="12:25", week_type="upper",
    proj=True, comp=False
)
bk = get_event_bookings()
print(f"Bookings in DB: {len(bk)}")

# Проверка grid
sched = get_schedule_grid("Понедельник", "upper")
print(f"\nSchedule entries: {len(sched)}")

# Проверка transfers_for_slot
tr_slot = get_transfers_for_slot("Понедельник", "10:50", "12:25", "upper")
print(f"Transfers for slot: {len(tr_slot)}")

# Проверка bookings_for_slot
bk_slot = get_bookings_for_slot("Понедельник", "10:50", "12:25", "upper")
print(f"Bookings for slot: {len(bk_slot)}")

print("\nALL OK")
