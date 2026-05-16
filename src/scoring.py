"""
Шаг 3. Модуль оценки (Cost Function).

Функции:
- calculate_penalty(...) — штраф за перемещение занятия в другую аудиторию.
- score_alternatives(...) — список альтернатив с штрафами и «% пригодности».
"""

from dataclasses import dataclass
from .search_engine import (
    get_valid_alternatives,
    get_lesson_info,
)


@dataclass
class ScoredRoom:
    """Аудитория-альтернатива с оценкой."""
    room_id: int
    name: str
    building: str
    floor: int
    capacity: int
    has_projector: bool
    has_computers: bool
    penalty: int          # штраф (меньше = лучше)
    match_percent: float  # процент пригодности (100 = идеально)


def calculate_penalty(
    original_building: str,
    original_floor: int,
    alt_building: str,
    alt_floor: int,
    alt_capacity: int,
    students_count: int,
    *,
    needs_projector: bool = False,
    needs_computers: bool = False,
    alt_has_projector: bool = False,
    alt_has_computers: bool = False,
) -> int:
    """
    Рассчитать штраф за перемещение занятия в альтернативную аудиторию.

    Компоненты:
    - Другой корпус:           +100
    - Разница в этажах:        + |orig_floor - alt_floor| * 5
    - Избыток вместимости:     + (alt_capacity - students_count) * 1
      (чтобы не сажать группу 15 чел в зал на 200)
    - Ненужное оборудование:   +10 если аудитория с компьютерами, а они не нужны
                               +5  если аудитория с проектором, а он не нужен
      (чтобы не занимать специализированные аудитории без необходимости)
    """
    penalty = 0

    # Логистика: корпус
    if original_building != alt_building:
        penalty += 100

    # Логистика: этажи
    floor_diff = abs(original_floor - alt_floor)
    penalty += floor_diff * 5

    # Нецелевое использование вместимости
    waste = alt_capacity - students_count
    if waste > 0:
        penalty += waste

    # Ненужное оборудование — мягкий штраф
    # Компьютеры: редкий ресурс, не занимать без нужды
    if not needs_computers and alt_has_computers:
        penalty += 10

    # Проектор: менее критично, но тоже не идеально
    if not needs_projector and alt_has_projector:
        penalty += 5

    return penalty


def score_alternatives(schedule_id: int) -> list[ScoredRoom]:
    """
    Оценить все подходящие альтернативы для занятия.

    Возвращает список ScoredRoom, отсортированный по возрастанию штрафа
    (лучшие — первыми).

    match_percent вычисляется относительно худшей и лучшей альтернативы:
        100% = лучший вариант (мин. штраф)
        0%   = худший вариант  (макс. штраф)
        промежуточные — линейная интерполяция
    """
    info = get_lesson_info(schedule_id)
    if info is None:
        raise ValueError(f"Занятие schedule_id={schedule_id} не найдено")

    alts = get_valid_alternatives(schedule_id)
    if not alts:
        return []

    orig_building = info["room_building"]
    orig_floor = info["room_floor"]
    students_count = info["students_count"]

    # Считаем штрафы
    scored = []
    for r in alts:
        p = calculate_penalty(
            original_building=orig_building,
            original_floor=orig_floor,
            alt_building=r["building"],
            alt_floor=r["floor"],
            alt_capacity=r["capacity"],
            students_count=students_count,
            needs_projector=bool(info["needs_projector"]),
            needs_computers=bool(info["needs_computers"]),
            alt_has_projector=bool(r["has_projector"]),
            alt_has_computers=bool(r["has_computers"]),
        )
        scored.append(ScoredRoom(
            room_id=r["id"],
            name=r["name"],
            building=r["building"],
            floor=r["floor"],
            capacity=r["capacity"],
            has_projector=r["has_projector"],
            has_computers=r["has_computers"],
            penalty=p,
            match_percent=0.0,  # заполним ниже
        ))

    # Конвертация штрафов в % пригодности
    penalties = [s.penalty for s in scored]
    min_p = min(penalties)
    max_p = max(penalties)

    for s in scored:
        if max_p == min_p:
            # Все одинаково хороши
            s.match_percent = 100.0
        else:
            s.match_percent = round(
                (1 - (s.penalty - min_p) / (max_p - min_p)) * 100, 1
            )

    # Сортировка: лучшие (меньший штраф) первыми
    scored.sort(key=lambda s: (s.penalty, -s.match_percent))

    return scored


# ──────────────────────────────────────────────
# CLI-тест
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import random
    import sqlite3
    import os

    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    sample_ids = [r["id"] for r in conn.execute("SELECT id FROM schedule LIMIT 30").fetchall()]
    conn.close()

    sid = random.choice(sample_ids)
    from .search_engine import get_lesson_info
    info = get_lesson_info(sid)

    print(f"=== Занятие: schedule_id={sid} ===")
    print(f"Предмет:  {info['lesson_title']} ({info['lesson_type']})")
    print(f"Группа:   {info['group_name']} ({info['students_count']} чел.)")
    print(f"Текущая:  {info['room_name']} (корп.{info['room_building']}, эт.{info['room_floor']})")
    print()

    scored = score_alternatives(sid)
    print(f"Найдено {len(scored)} альтернатив:\n")
    print(f"{'#':>3}  {'Аудитория':15s} {'Корп':5s} {'Эт':3s} {'Cap':>4s}  {'Штраф':>6s}  {'Совпад.':>8s}  Комментарий")
    print("-" * 110)
    for i, s in enumerate(scored[:15], 1):
        comment = ""
        if s.penalty == 0:
            comment = "← ИДЕАЛЬНО"
        elif s.building == info["room_building"]:
            comment = "тот же корпус"
        print(f"{i:3d}. {s.name:15s} {s.building:5s} {s.floor:3d} {s.capacity:4d}  {s.penalty:6d}  {s.match_percent:7.1f}%  {comment}")
    if len(scored) > 15:
        print(f"  ... и ещё {len(scored) - 15}")
