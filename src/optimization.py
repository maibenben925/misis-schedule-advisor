"""
Шаг 4. Глобальная оптимизация массовых переносов (Венгерский алгоритм).

Функции:
- mass_reallocate(schedule_ids) — оптимально перераспределить N занятий по M аудиториям.

Возвращает MassReallocationResult с:
  assignments:    {schedule_id: ScoredRoom}
  unassigned:     [schedule_id, ...] — кому не хватило места
  total_penalty:  суммарный штраф
  metrics:        статистика переноса
"""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import linear_sum_assignment

from .search_engine import (
    get_free_rooms,
    get_lesson_info,
    filter_rooms,
)
from .scoring import calculate_penalty, ScoredRoom


@dataclass
class MassReallocationResult:
    assignments: dict[int, ScoredRoom] = field(default_factory=dict)
    unassigned: list[int] = field(default_factory=list)
    total_penalty: int = 0
    avg_penalty: float = 0.0
    avg_match_percent: float = 0.0
    n_lessons: int = 0
    n_free_rooms: int = 0


def _build_cost_matrix(
    lessons: list[dict],
    free_rooms: list,
) -> tuple[np.ndarray, dict, dict]:
    """
    Построить матрицу стоимостей N×M.

    lessons: список dicts с инфой о занятиях
    free_rooms: список sqlite3.Row свободных аудиторий

    Returns:
        cost_matrix: np.ndarray[N, M]
        lesson_idx_map: {schedule_id: row_index}
        room_idx_map: {room_id: col_index}
    """
    n = len(lessons)
    m = len(free_rooms)

    BIG_COST = 10**9  # для невозможных назначений
    cost = np.full((n, m), BIG_COST, dtype=np.float64)

    lesson_idx_map = {}
    room_idx_map = {}

    for i, lesson in enumerate(lessons):
        lesson_idx_map[lesson["schedule_id"]] = i

        for j, room in enumerate(free_rooms):
            room_idx_map[room["id"]] = j

            # Hard constraints: проверяем вместимость и оборудование
            if room["capacity"] < lesson["students_count"]:
                continue
            if lesson["needs_projector"] and not room["has_projector"]:
                continue
            if lesson["needs_computers"] and not room["has_computers"]:
                continue

            # Cost = penalty из scoring
            cost[i, j] = calculate_penalty(
                original_building=lesson["room_building"],
                original_floor=lesson["room_floor"],
                alt_building=room["building"],
                alt_floor=room["floor"],
                alt_capacity=room["capacity"],
                students_count=lesson["students_count"],
                needs_projector=lesson["needs_projector"],
                needs_computers=lesson["needs_computers"],
                alt_has_projector=room["has_projector"],
                alt_has_computers=room["has_computers"],
            )

    return cost, lesson_idx_map, room_idx_map


def _build_super_cost_matrix(
    super_units: list[dict],
    free_rooms: list,
) -> tuple[np.ndarray, dict, dict]:
    """Матрица стоимостей для 'супер-уроков' (лекций с суммарными студентами)."""
    n = len(super_units)
    m = len(free_rooms)

    BIG_COST = 10**9
    cost = np.full((n, m), BIG_COST, dtype=np.float64)

    unit_idx_map = {}
    room_idx_map = {}

    for i, unit in enumerate(super_units):
        unit_idx_map[i] = i

        for j, room in enumerate(free_rooms):
            room_idx_map[room["id"]] = j

            # Hard constraints: суммарная вместимость
            if room["capacity"] < unit["students_count"]:
                continue
            if unit["needs_projector"] and not room["has_projector"]:
                continue
            if unit["needs_computers"] and not room["has_computers"]:
                continue

            cost[i, j] = calculate_penalty(
                original_building=unit["room_building"],
                original_floor=unit["room_floor"],
                alt_building=room["building"],
                alt_floor=room["floor"],
                alt_capacity=room["capacity"],
                students_count=unit["students_count"],
                needs_projector=unit["needs_projector"],
                needs_computers=unit["needs_computers"],
                alt_has_projector=room["has_projector"],
                alt_has_computers=room["has_computers"],
            )

    return cost, unit_idx_map, room_idx_map


def _build_super_scored_rooms(
    cost_matrix: np.ndarray,
    row_indices: list[int],
    col_indices: list[int],
    free_rooms: list,
    super_units: list[dict],
    unit_idx_map: dict,
    room_idx_map: dict,
) -> dict[int, ScoredRoom]:
    """ScoredRoom для супер-уроков: одна аудитория → все schedule_ids лекции."""
    assignments = {}

    for row_idx, col_idx in zip(row_indices, col_indices):
        penalty = int(cost_matrix[row_idx, col_idx])

        # Пропускаем невозможные назначения (BIG_COST)
        if penalty >= 10**9:
            continue

        unit = super_units[row_idx]
        room = free_rooms[col_idx]

        # Match %: относительный — 100% = лучший вариант, 0% = худший
        row_costs = cost_matrix[row_idx]
        valid_costs = row_costs[row_costs < 10**9]
        if len(valid_costs) > 1:
            min_c, max_c = valid_costs.min(), valid_costs.max()
            if max_c > min_c:
                match_pct = round((1 - (penalty - min_c) / (max_c - min_c)) * 100, 1)
            else:
                match_pct = 100.0
        else:
            match_pct = 100.0

        scored = ScoredRoom(
            room_id=room["id"],
            name=room["name"],
            building=room["building"],
            floor=room["floor"],
            capacity=room["capacity"],
            has_projector=room["has_projector"],
            has_computers=room["has_computers"],
            penalty=penalty,
            match_percent=match_pct,
        )

        # Назначаем ОДНУ аудиторию всем schedule_ids этого супер-урока
        for sid in unit["schedule_ids"]:
            assignments[sid] = scored

    return assignments


def _build_scored_rooms(
    cost_matrix: np.ndarray,
    row_indices: list[int],
    col_indices: list[int],
    free_rooms: list,
    lessons: list[dict],
    lesson_idx_map: dict,
    room_idx_map: dict,
) -> dict[int, ScoredRoom]:
    """Построить ScoredRoom для назначенных пар."""
    assignments = {}

    for row_idx, col_idx in zip(row_indices, col_indices):
        sid = None
        for s_id, idx in lesson_idx_map.items():
            if idx == row_idx:
                sid = s_id
                break
        if sid is None:
            continue

        lesson = lessons[row_idx]
        room = free_rooms[col_idx]
        penalty = int(cost_matrix[row_idx, col_idx])

        # Вычисляем % пригодности — нужен min/max по этой строке
        row_costs = cost_matrix[row_idx]
        valid_costs = row_costs[row_costs < 10**9]
        if len(valid_costs) > 1:
            min_c, max_c = valid_costs.min(), valid_costs.max()
            if max_c > min_c:
                match_pct = round((1 - (penalty - min_c) / (max_c - min_c)) * 100, 1)
            else:
                match_pct = 100.0
        else:
            match_pct = 100.0

        assignments[sid] = ScoredRoom(
            room_id=room["id"],
            name=room["name"],
            building=room["building"],
            floor=room["floor"],
            capacity=room["capacity"],
            has_projector=room["has_projector"],
            has_computers=room["has_computers"],
            penalty=penalty,
            match_percent=match_pct,
        )

    return assignments


def mass_reallocate(schedule_ids: list[int]) -> MassReallocationResult:
    """
    Оптимально перераспределить N занятий по свободным аудиториям.

    Алгоритм:
    1. Собрать информацию о всех занятиях.
    2. Разбить занятия по уникальным временным слотам (weekday, start, end, week_type).
    3. Для каждого слота независимо:
       a. Найти свободные аудитории именно для этого слота.
       b. Построить матрицу стоимостей и применить венгерский алгоритм.
    4. Объединить результаты.
    """
    if not schedule_ids:
        return MassReallocationResult()

    # 1. Информация о занятиях
    lessons = []
    for sid in schedule_ids:
        info = get_lesson_info(sid)
        if info is None:
            raise ValueError(f"Занятие schedule_id={sid} не найдено")
        lessons.append({
            "schedule_id": sid,
            "students_count": info["students_count"],
            "needs_projector": bool(info["needs_projector"]),
            "needs_computers": bool(info["needs_computers"]),
            "room_building": info["room_building"],
            "room_floor": info["room_floor"],
            "room_id": info["room_id"],
            "weekday": info["weekday"],
            "start": info["start"],
            "end": info["end"],
            "week_type": info["week_type"],
            "lesson_title": info["lesson_title"],
            "lesson_type": info["lesson_type"],
            "group_name": info["group_name"],
        })

    # 2. Группируем занятия по временным слотам
    time_slots: dict[tuple, list[dict]] = {}
    for lesson in lessons:
        key = (lesson["weekday"], lesson["start"], lesson["end"], lesson["week_type"])
        time_slots.setdefault(key, []).append(lesson)

    # 3. Для каждого слота — независимая оптимизация
    all_assignments: dict[int, ScoredRoom] = {}
    all_unassigned: list[int] = []
    total_penalty = 0

    for slot_key, slot_lessons in time_slots.items():
        weekday, start, end, week_type = slot_key

        # КРИТИЧНО: группируем по lesson_id (для лекций — объединяем группы)
        lesson_groups: dict[int, list[dict]] = {}
        for l in slot_lessons:
            info = get_lesson_info(l["schedule_id"])
            lid = info["lesson_id"]
            lesson_groups.setdefault(lid, []).append(l)

        # Создаём "супер-уроки": для лекций суммируем студентов
        super_units: list[dict] = []
        for lid, group_lessons in lesson_groups.items():
            if len(group_lessons) == 1:
                # Обычное занятие — одна группа
                super_units.append({
                    "schedule_ids": [group_lessons[0]["schedule_id"]],
                    "students_count": group_lessons[0]["students_count"],
                    "needs_projector": group_lessons[0]["needs_projector"],
                    "needs_computers": group_lessons[0]["needs_computers"],
                    "room_building": group_lessons[0]["room_building"],
                    "room_floor": group_lessons[0]["room_floor"],
                    "room_id": group_lessons[0]["room_id"],
                    "lesson_title": group_lessons[0]["lesson_title"],
                    "lesson_type": group_lessons[0]["lesson_type"],
                    "group_name": group_lessons[0]["group_name"],
                })
            else:
                # Лекция: несколько групп → одна аудитория на всех
                total_students = sum(l["students_count"] for l in group_lessons)
                # Объединяем требования (проектор нужен, если хотя бы одной группе)
                needs_proj = any(l["needs_projector"] for l in group_lessons)
                needs_comp = any(l["needs_computers"] for l in group_lessons)
                super_units.append({
                    "schedule_ids": [l["schedule_id"] for l in group_lessons],
                    "students_count": total_students,
                    "needs_projector": needs_proj,
                    "needs_computers": needs_comp,
                    "room_building": group_lessons[0]["room_building"],
                    "room_floor": group_lessons[0]["room_floor"],
                    "room_id": group_lessons[0]["room_id"],
                    "lesson_title": group_lessons[0]["lesson_title"],
                    "lesson_type": group_lessons[0]["lesson_type"],
                    "group_name": ", ".join(l["group_name"] for l in group_lessons),
                })

        excluded_ids = [u["room_id"] for u in super_units]

        # Свободные аудитории именно для этого слота
        free_rooms = get_free_rooms(
            weekday=weekday, start=start, end=end, week_type=week_type,
        )
        free_rooms = [r for r in free_rooms if r["id"] not in excluded_ids]

        n = len(super_units)
        m = len(free_rooms)

        if m == 0:
            for u in super_units:
                all_unassigned.extend(u["schedule_ids"])
            continue

        # Матрица стоимостей для супер-уроков
        cost_matrix, unit_idx_map, room_idx_map = _build_super_cost_matrix(
            super_units, free_rooms
        )

        # Венгерский алгоритм
        row_indices, col_indices = linear_sum_assignment(cost_matrix)

        # Назначения для этого слота
        slot_assignments = _build_super_scored_rooms(
            cost_matrix, list(row_indices), list(col_indices),
            free_rooms, super_units, unit_idx_map, room_idx_map,
        )

        all_assignments.update(slot_assignments)

        # Неназначенные в этом слоте
        assigned_unit_indices = set()
        for u_idx, u_info in unit_idx_map.items():
            for r_idx, c_idx in zip(row_indices, col_indices):
                if u_info == r_idx:
                    assigned_unit_indices.add(u_idx)
                    break
        for i, u in enumerate(super_units):
            if i not in assigned_unit_indices:
                all_unassigned.extend(u["schedule_ids"])

    # 4. Итоги
    total_penalty = sum(s.penalty for s in all_assignments.values())
    n_assigned = len(all_assignments)
    avg_penalty = total_penalty / n_assigned if n_assigned else 0
    avg_match = (
        sum(s.match_percent for s in all_assignments.values()) / n_assigned
        if n_assigned else 0
    )

    return MassReallocationResult(
        assignments=all_assignments,
        unassigned=all_unassigned,
        total_penalty=total_penalty,
        avg_penalty=round(avg_penalty, 1),
        avg_match_percent=round(avg_match, 1),
        n_lessons=len(schedule_ids),
        n_free_rooms=0,  # зависит от слота, не имеет единого значения
    )


# ──────────────────────────────────────────────
# CLI-тест
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sqlite3
    import os

    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("=== ТЕСТ 1: Перенос всех занятий из корпуса А ===\n")

    # Находим все занятия, идущие в корпусе А в понедельник
    rows = c.execute("""
        SELECT s.id, r.name, r.building, s.weekday, s.start, s.end, s.week_type
        FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building = 'А' AND s.weekday = 'Понедельник' AND s.week_type = 'upper'
        LIMIT 10
    """).fetchall()

    sids = [r["id"] for r in rows]
    print(f"Занятий для переноса: {len(sids)}")
    for r in rows:
        print(f"  #{r['id']:4d} | {r['name']:15s} | {r['weekday']} {r['start'][11:16]}-{r['end'][11:16]}")

    result = mass_reallocate(sids)

    print(f"\n--- Результат ---")
    print(f"Назначено:    {len(result.assignments)}")
    print(f"Не назначено: {len(result.unassigned)}")
    print(f"Суммарный штраф: {result.total_penalty}")
    print(f"Средний штраф:   {result.avg_penalty}")
    print(f"Средний match:   {result.avg_match_percent}%")
    print(f"Свободных аудиторий: {result.n_free_rooms}")

    if result.assignments:
        print(f"\n{'#':>3}  {'Было':15s}  {'Стало':15s}  {'Штраф':>6s}  {'%':>7s}  Комментарий")
        print("-" * 100)
        for i, sid in enumerate(sorted(result.assignments.keys()), 1):
            s = result.assignments[sid]
            old_info = get_lesson_info(sid)
            old_room = old_info["room_name"]
            same_building = " ← тот же корпус" if s.building == old_info["room_building"] else ""
            print(f"{i:3d}. {old_room:15s} → {s.name:15s}  {s.penalty:6d}  {s.match_percent:6.1f}%{same_building}")

    if result.unassigned:
        print(f"\nНе хватило места:")
        for sid in result.unassigned:
            info = get_lesson_info(sid)
            print(f"  #{sid}: {info['lesson_title']} ({info['group_name']})")

    conn.close()
