"""
Нормализация данных перед загрузкой в БД:
1. Убирает подгруппы из title (1 п.г., 2 п.г. и т.д.)
2. Исправляет баг API: название группы вместо аудитории → 'Онлайн'
3. Схлопывает дубликаты (одинаковые занятия)
4. Обрезает секунды в start/end
5. Сохраняет очищенный JSON
"""
import json
import re
from pathlib import Path

INPUT_PATH = Path(r"D:\misis\8-semester\diploma-testing\data\raw\schedule_all_groups_with_weeks.json")
OUTPUT_PATH = Path(r"D:\misis\8-semester\diploma-testing\data\raw\schedule_clean.json")

def clean_title(title):
    """'1 п.г. Объектно-ориентированное программирование' → 'Объектно-ориентированное программирование'"""
    title = re.sub(r'^\d+(,\s*\d+)*\s*п\.г\.\s*', '', title)
    # "с 08:30 до 10:00 Физическая культура и спорт" → "Физическая культура и спорт"
    title = re.sub(r'^с\s+\d{2}:\d{2}\s+до\s+\d{2}:\d{2}\s+', '', title)
    return title

def clean_location(location, group_name):
    """Если аудитория = название группы → это баг API, заменяем на 'Онлайн'."""
    if location == group_name:
        return "Онлайн"
    return location

def clean_datetime(dt_str):
    """'2026-01-12T09:00:07+03:00' → '2026-01-12T09:00:00+03:00'"""
    # Обрезаем секунды
    base = dt_str[:19]  # '2026-01-12T09:00:07'
    tz = dt_str[19:]    # '+03:00'
    return base[:17] + '00' + tz  # '2026-01-12T09:00:00+03:00'

with open(INPUT_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Исходно: {len(data)} записей")

# Шаг 1: Чистим каждое занятие
for l in data:
    l['title'] = clean_title(l['title'])
    l['location'] = clean_location(l['location'], l['source_name'])
    l['start'] = clean_datetime(l['start'])
    l['end'] = clean_datetime(l['end'])

# Шаг 2: Схлопываем дубликаты
# Ключ уникальности: group + title + type + teacher + weekday + start + end + week_type + location
seen = set()
cleaned = []
duplicates = 0

for l in data:
    key = (
        l['source_name'],
        l['title'],
        l['type'],
        l['teacher'] or '',
        l['weekday'],
        l['start'],
        l['end'],
        l['week_type'],
        l['location'],
    )
    if key in seen:
        duplicates += 1
    else:
        seen.add(key)
        cleaned.append(l)

print(f"Удалено дублей: {duplicates}")
print(f"Осталось записей: {len(cleaned)}")

with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(cleaned, f, ensure_ascii=False, indent=2)

print(f"\nСохранено: {OUTPUT_PATH}")
