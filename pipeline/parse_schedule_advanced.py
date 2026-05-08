"""
Расширенный парсер расписания с API schedule.misis.club

Возможности:
- Парсинг расписания для нескольких групп
- Парсинг расписания для нескольких аудиторий
- Анализ и статистика
- Сохранение в различных форматах (JSON, CSV)
"""

import os
import re
import csv
import json
import requests
from datetime import datetime, time
from pathlib import Path
from typing import List, Dict, Optional, Set
import icalendar
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class Lesson:
    """Модель занятия"""
    title: str  # Название дисциплины
    type: str  # Тип: Лекционные, Практические, Лабораторные
    teacher: str  # Преподаватель
    location: str  # Аудитория
    start: str  # Дата-время начала (ISO формат)
    end: str  # Дата-время окончания (ISO формат)
    weekday: str  # День недели
    week_type: str  # Тип недели: alternating/weekly
    source_type: str  # 'group' или 'location'
    source_name: str  # Название группы или аудитории


def parse_ical_to_lessons(ical_data: bytes, source_type: str, source_name: str) -> List[Dict]:
    """Парсит iCal данные в список занятий."""
    cal = icalendar.Calendar.from_ical(ical_data)
    lessons = []
    
    weekday_map = {
        0: 'Понедельник', 1: 'Вторник', 2: 'Среда',
        3: 'Четверг', 4: 'Пятница', 5: 'Суббота', 6: 'Воскресенье'
    }
    
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        
        summary = str(component.get('SUMMARY', ''))
        location = str(component.get('LOCATION', ''))
        dtstart = component.get('DTSTART')
        dtend = component.get('DTEND')
        rrule = component.get('RRULE')
        
        if dtstart is None or dtend is None:
            continue
        
        start_dt = dtstart.dt if hasattr(dtstart, 'dt') else dtstart
        end_dt = dtend.dt if hasattr(dtend, 'dt') else dtend
        
        if not hasattr(start_dt, 'hour'):
            start_dt = datetime.combine(start_dt, time.min)
            end_dt = datetime.combine(end_dt, time.min)
        
        weekday = weekday_map.get(start_dt.weekday(), 'Unknown')
        
        week_type = "weekly"
        if rrule:
            interval = rrule.get("INTERVAL", [1])
            try:
                interval_val = interval[0] if hasattr(interval, '__getitem__') else interval
                if int(interval_val) == 2:
                    week_type = "alternating"
            except (ValueError, TypeError):
                pass
        
        title, lesson_type, teacher = parse_summary(summary)
        
        lesson = Lesson(
            title=title, type=lesson_type, teacher=teacher,
            location=location if location else source_name,
            start=start_dt.isoformat(), end=end_dt.isoformat(),
            weekday=weekday, week_type=week_type,
            source_type=source_type, source_name=source_name
        )
        
        lessons.append(asdict(lesson))
    
    return lessons


def parse_summary(summary: str) -> tuple:
    """Разбирает поле SUMMARY на составные части.
    
    Формат SUMMARY: "Название (уточнение) / Название (уточнение) (Тип) [Преподаватель]"
    Пример: "Foreign Language (English / Russian) / Иностранный язык (Английский / Русский) (Практические) [Сюй М. В.]"
    
    Тип занятия — это последние скобки перед [преподаватель].
    Ищем все скобки и проверяем каждую на стандартный тип.
    """
    VALID_TYPES = {'Лекционные', 'Практические', 'Лабораторные',
                   'Лекция', 'Практика', 'Лабораторная',
                   'лекционные', 'практические', 'лабораторные'}
    
    title = ''
    lesson_type = ''
    teacher = ''

    summary = summary.strip()

    # Извлекаем преподавателя из [скобок]
    teacher_match = re.search(r'\[([^\]]+)\]', summary)
    if teacher_match:
        teacher = clean_teacher_name(teacher_match.group(1))
        summary = summary[:teacher_match.start()].strip()

    # Находим ВСЕ скобки и ищем тип занятия
    # Ищем стандартный тип — берём последнее совпадение
    all_parens = list(re.finditer(r'\(([^)]+)\)', summary))
    
    # Идём с конца — тип обычно в последних скобках
    for match in reversed(all_parens):
        potential_type = match.group(1).strip()
        if potential_type in VALID_TYPES:
            lesson_type = potential_type
            # Убираем скобки с типом из названия
            summary = summary[:match.start()].strip()
            break
    
    # Убираем любые оставшиеся скобки — они часть названия
    # (но уже внутри title, не трогаем их)
    
    title = summary.strip()
    return title, lesson_type, teacher


def clean_teacher_name(teacher: str) -> str:
    """Очищает имя преподавателя от лишних пробелов.
    
    'Петр ов А. Е.' -> 'Петров А. Е.'
    Убирает пробелы ВНУТРИ слов, но оставляет перед инициалами (буква + точка).
    """
    if not teacher:
        return ""
    # Убираем пробел между буквами, если после второй буквы НЕТ точки
    # и это не конец строки (т.е. за ней следует ещё буква или запятая)
    cleaned = re.sub(r'(\w)\s+(\w)(?=\w)', r'\1\2', teacher)
    return cleaned.strip()


def fetch_schedule(url: str, name: str, source_type: str) -> List[Dict]:
    """Получает расписание по URL."""
    print(f"📡 Запрос: {name}")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        lessons = parse_ical_to_lessons(response.content, source_type, name)
        print(f"   ✅ Получено {len(lessons)} занятий")
        
        return lessons
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Ошибка: {e}")
        return []


def fetch_group_schedule(group_name: str) -> List[Dict]:
    """Получает расписание для группы"""
    url = f"https://schedule.misis.club/api/ical/group/{group_name}"
    return fetch_schedule(url, group_name, 'group')


def fetch_location_schedule(room_name: str) -> List[Dict]:
    """Получает расписание для аудитории"""
    url = f"https://schedule.misis.club/api/ical/location/{room_name}"
    return fetch_schedule(url, room_name, 'location')


def save_lessons_json(lessons: List[Dict], filepath: Path):
    """Сохраняет занятия в JSON"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(lessons, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON сохранен: {filepath}")


def save_lessons_csv(lessons: List[Dict], filepath: Path):
    """Сохраняет занятия в CSV"""
    if not lessons:
        return
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['title', 'type', 'teacher', 'location', 'start', 'end', 
                  'weekday', 'week_type', 'source_type', 'source_name']
    
    with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lessons)
    
    print(f"💾 CSV сохранен: {filepath}")


def analyze_schedule(lessons: List[Dict], title: str):
    """Анализирует расписание и выводит статистику"""
    if not lessons:
        print(f"\n📊 {title}: Нет данных для анализа")
        return
    
    print(f"\n{'='*70}")
    print(f"📊 Анализ: {title}")
    print(f"{'='*70}")
    
    print(f"\n📚 Всего занятий: {len(lessons)}")
    
    unique_courses = set(l['title'] for l in lessons if l['title'])
    print(f"📖 Уникальных дисциплин: {len(unique_courses)}")
    
    by_type = defaultdict(int)
    for l in lessons:
        if l['type']:
            by_type[l['type']] += 1
    
    print(f"\n📋 По типам занятий:")
    for lesson_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"   {lesson_type}: {count}")
    
    by_weekday = defaultdict(int)
    for l in lessons:
        by_weekday[l['weekday']] += 1
    
    weekday_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    
    print(f"\n📅 По дням недели:")
    for day in weekday_order:
        if day in by_weekday:
            print(f"   {day}: {by_weekday[day]}")
    
    if lessons and lessons[0]['source_type'] == 'group':
        by_location = defaultdict(int)
        for l in lessons:
            loc = l['location'] if l['location'] else 'Не указана'
            by_location[loc] += 1
        
        print(f"\n🏫 По аудиториям (топ-15):")
        for loc, count in sorted(by_location.items(), key=lambda x: -x[1])[:15]:
            print(f"   {loc}: {count}")
    
    by_teacher = defaultdict(int)
    for l in lessons:
        if l['teacher']:
            by_teacher[l['teacher']] += 1
    
    print(f"\n👨‍🏫 Топ преподавателей:")
    for teacher, count in sorted(by_teacher.items(), key=lambda x: -x[1])[:10]:
        print(f"   {teacher}: {count}")
    
    print(f"\n{'='*70}\n")


def collect_all_rooms(lessons: List[Dict]) -> Set[str]:
    """Собирает все уникальные аудитории из расписания"""
    rooms = set()
    for l in lessons:
        if l['location'] and l['location'] != 'Онлайн':
            rooms.add(l['location'])
    return rooms


def parse_groups_from_info(filepath: Path) -> List[str]:
    """Парсит список групп из info.txt"""
    groups = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Разделяем на секции
    sections = content.split('----------')
    groups_section = sections[0]
    
    for line in groups_section.split('\n'):
        line = line.strip()
        if not line or line.startswith(('1 курс', '2 курс', '3 курс', '4 курс', 
                                        'Магистратура', 'Обратите')):
            continue
        for g in line.split(','):
            g = g.strip()
            if g:
                groups.append(g)
    
    return groups


def parse_rooms_from_info(filepath: Path) -> List[str]:
    """Парсит список аудиторий из info.txt"""
    rooms = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Берём часть после ----------
    sections = content.split('----------')
    if len(sections) < 2:
        return rooms
    
    rooms_section = sections[1]
    
    for line in rooms_section.split('\n'):
        line = line.strip()
        if not line or line.startswith(('Корпус', 'Обратите')):
            continue
        for r in line.split(','):
            r = r.strip()
            if r:
                rooms.append(r)
    
    return rooms


def main():
    """Главная функция"""
    # Пути
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data" / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    info_file = project_root / "info.txt"
    
    print("🎓 Парсинг расписания с schedule.misis.club")
    print("="*70)
    
    # === Читаем списки из info.txt ===
    if info_file.exists():
        print("\n📋 Чтение списков из info.txt...")
        all_groups = parse_groups_from_info(info_file)
        all_rooms = parse_rooms_from_info(info_file)
        print(f"   📚 Групп: {len(all_groups)}")
        print(f"   🏫 Аудиторий: {len(all_rooms)}")
    else:
        print(f"❌ Файл {info_file} не найден!")
        return
    
    # === ЧАСТЬ 1: Расписание для групп ===
    print("\n📚 ЧАСТЬ 1: Расписание для групп")
    print("-" * 70)
    
    all_group_lessons = []
    groups_with_schedule = 0
    
    for i, group in enumerate(all_groups, 1):
        print(f"[{i}/{len(all_groups)}]", end=" ")
        lessons = fetch_group_schedule(group)
        if lessons:
            groups_with_schedule += 1
        all_group_lessons.extend(lessons)
    
    print(f"\n✅ Групп с расписанием: {groups_with_schedule}/{len(all_groups)}")
    print(f"📚 Всего занятий: {len(all_group_lessons)}")
    
    # Сохраняем все групповые занятия
    if all_group_lessons:
        save_lessons_json(all_group_lessons, data_dir / "schedule_all_groups.json")
        save_lessons_csv(all_group_lessons, data_dir / "schedule_all_groups.csv")
    
    # === ЧАСТЬ 2: Расписание для аудиторий ===
    print("\n🏛 ЧАСТЬ 2: Расписание для аудиторий")
    print("-" * 70)
    
    all_room_lessons = []
    rooms_with_schedule = 0
    found_rooms_from_groups = set()
    
    # Собираем аудитории из расписания групп
    for l in all_group_lessons:
        if l['location'] and l['location'] != 'Онлайн':
            found_rooms_from_groups.add(l['location'])
    
    print(f"\n🔍 Найдено аудиторий из расписания групп: {len(found_rooms_from_groups)}")
    
    for i, room in enumerate(all_rooms, 1):
        print(f"[{i}/{len(all_rooms)}]", end=" ")
        lessons = fetch_location_schedule(room)
        if lessons:
            rooms_with_schedule += 1
        all_room_lessons.extend(lessons)
    
    print(f"\n✅ Аудиторий с расписанием: {rooms_with_schedule}/{len(all_rooms)}")
    print(f"📚 Всего занятий: {len(all_room_lessons)}")
    
    # Сохраняем все занятия аудиторий
    if all_room_lessons:
        save_lessons_json(all_room_lessons, data_dir / "schedule_all_locations.json")
        save_lessons_csv(all_room_lessons, data_dir / "schedule_all_locations.csv")
    
    # === ЧАСТЬ 3: Итоговая статистика ===
    print("\n📊 ЧАСТЬ 3: Итоговая статистика")
    print("-" * 70)
    
    all_lessons = all_group_lessons + all_room_lessons
    if all_lessons:
        analyze_schedule(all_lessons, "Общее расписание")
        
        # Сохраняем всё вместе
        save_lessons_json(all_lessons, data_dir / "schedule_complete.json")
        save_lessons_csv(all_lessons, data_dir / "schedule_complete.csv")
    
    # Список всех найденных аудиторий
    all_rooms_found = found_rooms_from_groups | set(all_rooms)
    print(f"\n🏫 Все найденные аудитории ({len(all_rooms_found)}):")
    for room in sorted(all_rooms_found):
        print(f"   {room}")
    
    # Итоги
    print(f"\n{'='*70}")
    print(f"✅ Парсинг завершён!")
    print(f"📁 Данные сохранены в: {data_dir}")
    print(f"📚 Групп обработано: {groups_with_schedule}/{len(all_groups)}")
    print(f"🏫 Аудиторий обработано: {rooms_with_schedule}/{len(all_rooms)}")
    print(f"📝 Всего занятий: {len(all_lessons)}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
