import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import get_schedule_grouped, ensure_tables
ensure_tables()
data = get_schedule_grouped('Понедельник', 'upper')
print(f"Schedule entries: {len(data)}")
lectures = [d for d in data if d['lesson_type'] == 'Лекционные']
print(f"Lectures: {len(lectures)}")
for l in lectures[:5]:
    print(f"  {l['room_name']:15s} {l['start']} | groups: {l['group_display']}")
print("OK")
