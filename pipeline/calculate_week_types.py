"""
Скрипт для определения верхней/нижней недели в расписании.

Логика:
- Семестр начинается с верхней недели (upper)
- Первая неделя семестра: 2026-01-12 (Пн)
- Чередование: upper → lower → upper → lower ...
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# Дата начала семестра (первая неделя — верхняя)
SEMESTER_START = datetime(2026, 1, 12, tzinfo=datetime.now().astimezone().tzinfo)  # Пн, 12 янв 2026


def get_week_number_from_start(date: datetime) -> int:
    """
    Возвращает номер недели от начала семестра (1-based).
    12 января = неделя 1
    19 января = неделя 2
    и т.д.
    """
    delta = date - SEMESTER_START
    weeks = delta.days // 7 + 1  # +1 потому что первая неделя = 1
    return weeks


def get_week_type(date: datetime) -> str:
    """
    Определяет тип недели:
    - upper: нечётные недели от начала (1, 3, 5...)
    - lower: чётные недели от начала (2, 4, 6...)
    - weekly: каждую неделю (INTERVAL=1, редкое)
    """
    week_num = get_week_number_from_start(date)
    return "upper" if week_num % 2 == 1 else "lower"


def get_semester_week(date: datetime) -> int:
    """Номер недели семестра (1-based)"""
    return get_week_number_from_start(date)


def process_schedule(input_file: Path, output_file: Path):
    """
    Читает расписание, добавляет week_type (upper/lower), сохраняет.
    """
    print(f"📂 Чтение: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"📝 Всего занятий: {len(data)}")
    
    # Статистика
    week_type_counter = Counter()
    semester_week_counter = Counter()
    fixed = 0
    
    for lesson in data:
        # Парсим дату начала
        start_str = lesson['start']
        start_dt = datetime.fromisoformat(start_str)
        
        # Определяем неделю
        sem_week = get_semester_week(start_dt)
        week_type = get_week_type(start_dt)
        
        # Обновляем поле week_type
        lesson['week_type'] = week_type
        lesson['semester_week'] = sem_week
        
        week_type_counter[week_type] += 1
        semester_week_counter[sem_week] += 1
        fixed += 1
    
    print(f"✅ Обработано: {fixed} занятий")
    
    # Статистика по неделям
    print(f"\n📊 Распределение по типу недели:")
    for wt, count in sorted(week_type_counter.items()):
        print(f"   {wt}: {count}")
    
    print(f"\n📅 Распределение по неделям семестра:")
    for week_num, count in sorted(semester_week_counter.items()):
        print(f"   Неделя {week_num}: {count} ({week_type_counter.get('upper' if week_num % 2 == 1 else 'lower', 0)})")
    
    # Сохраняем
    print(f"\n💾 Сохранение: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Готово!")


def main():
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data" / "raw"
    
    print("🎓 Определение верхней/нижней недели")
    print("=" * 60)
    print(f"📅 Начало семестра: {SEMESTER_START.strftime('%d.%m.%Y')} (Пн)")
    print("=" * 60)
    
    # Обрабатываем разные файлы
    files_to_process = [
        "schedule_all_groups.json",
        "schedule_all_locations.json",
        "schedule_complete.json",
    ]
    
    for filename in files_to_process:
        input_file = data_dir / filename
        if input_file.exists():
            output_name = filename.replace('.json', '_with_weeks.json')
            output_file = data_dir / output_name
            print(f"\n{'='*60}")
            print(f"📋 Файл: {filename}")
            print(f"{'='*60}")
            process_schedule(input_file, output_file)
        else:
            print(f"\n⏭ Пропуск: {filename} не найден")
    
    print(f"\n{'='*60}")
    print("✅ Все файлы обработаны!")


if __name__ == "__main__":
    main()
