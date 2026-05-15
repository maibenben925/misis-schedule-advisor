"""
Сравнение стратегий назначения аудиторий: Random, Greedy, Hungarian.

Сценарии от простых (1 занятие) до масштабных (закрытие корпуса на 2 недели).

Запуск:
    python src/benchmark.py                          -- все сценарии
    python src/benchmark.py --scenario 3             -- только сценарий 3
    python src/benchmark.py --custom А Понедельник upper
    python -m src.benchmark                          -- альтернативный способ
"""

from __future__ import annotations

import sys
from pathlib import Path
import random
import time
import sqlite3
import os
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from scipy.optimize import linear_sum_assignment

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "src"

from .search_engine import get_free_rooms, get_lesson_info
from .scoring import calculate_penalty, ScoredRoom

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
BASE_MONDAY = date(2026, 1, 12)

BIG_COST = 10**9


@dataclass
class StrategyResult:
    name: str
    total_penalty: int
    avg_penalty: float
    n_assigned: int
    n_unassigned: int
    elapsed_ms: float
    penalties: list[int]
    same_building_pct: float
    match_pcts: list[float]


def _wd_to_date(weekday_name: str) -> str:
    idx = WEEKDAYS.index(weekday_name)
    return str(BASE_MONDAY + timedelta(days=idx))


def _to_iso(t: str, weekday: str) -> str:
    return f"{_wd_to_date(weekday)}T{t}:00+03:00"


def _get_lessons_for_relocation(building: str, weekday: str, week_type: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.id AS schedule_id, s.lesson_id, s.weekday, s.start, s.end, s.week_type,
               l.needs_projector, l.needs_computers,
               g.students_count, g.name AS group_name,
               r.building AS room_building, r.floor AS room_floor, r.id AS room_id
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building = ? AND s.weekday = ? AND s.week_type = ?
    """, (building, weekday, week_type)).fetchall()
    conn.close()

    lessons = []
    for r in rows:
        lessons.append({
            "schedule_id": r["schedule_id"],
            "lesson_id": r["lesson_id"],
            "students_count": r["students_count"],
            "needs_projector": bool(r["needs_projector"]),
            "needs_computers": bool(r["needs_computers"]),
            "room_building": r["room_building"],
            "room_floor": r["room_floor"],
            "room_id": r["room_id"],
            "weekday": r["weekday"],
            "start": r["start"],
            "end": r["end"],
            "week_type": r["week_type"],
            "group_name": r["group_name"],
        })
    return lessons


def _get_lessons_for_relocation_building(building: str, week_types: list[str] | None = None) -> list[dict]:
    if week_types is None:
        week_types = ["upper", "lower"]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    placeholders_wt = ",".join("?" for _ in week_types)
    rows = conn.execute(f"""
        SELECT s.id AS schedule_id, s.lesson_id, s.weekday, s.start, s.end, s.week_type,
               l.needs_projector, l.needs_computers,
               g.students_count, g.name AS group_name,
               r.building AS room_building, r.floor AS room_floor, r.id AS room_id
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building = ? AND s.week_type IN ({placeholders_wt})
    """, [building] + week_types).fetchall()
    conn.close()

    lessons = []
    for r in rows:
        lessons.append({
            "schedule_id": r["schedule_id"],
            "lesson_id": r["lesson_id"],
            "students_count": r["students_count"],
            "needs_projector": bool(r["needs_projector"]),
            "needs_computers": bool(r["needs_computers"]),
            "room_building": r["room_building"],
            "room_floor": r["room_floor"],
            "room_id": r["room_id"],
            "weekday": r["weekday"],
            "start": r["start"],
            "end": r["end"],
            "week_type": r["week_type"],
            "group_name": r["group_name"],
        })
    return lessons


def _build_super_units(slot_lessons: list[dict]) -> list[dict]:
    lesson_groups: dict[int, list[dict]] = {}
    for l in slot_lessons:
        lesson_groups.setdefault(l["lesson_id"], []).append(l)

    super_units = []
    for lid, group_lessons in lesson_groups.items():
        if len(group_lessons) == 1:
            gl = group_lessons[0]
            super_units.append({
                "schedule_ids": [gl["schedule_id"]],
                "students_count": gl["students_count"],
                "needs_projector": gl["needs_projector"],
                "needs_computers": gl["needs_computers"],
                "room_building": gl["room_building"],
                "room_floor": gl["room_floor"],
                "room_id": gl["room_id"],
            })
        else:
            total_students = sum(l["students_count"] for l in group_lessons)
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
            })
    return super_units


def _build_cost_matrix(units: list[dict], rooms: list) -> np.ndarray:
    n = len(units)
    m = len(rooms)
    cost = np.full((n, m), BIG_COST, dtype=np.float64)

    for i, unit in enumerate(units):
        for j, room in enumerate(rooms):
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
    return cost


def _penalty_for_unit(unit: dict, room) -> int:
    if room["capacity"] < unit["students_count"]:
        return BIG_COST
    if unit["needs_projector"] and not room["has_projector"]:
        return BIG_COST
    if unit["needs_computers"] and not room["has_computers"]:
        return BIG_COST
    return calculate_penalty(
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


def _compute_match_pcts(penalties: list[int], all_penalties_per_unit: list[list[int]]) -> list[float]:
    if not penalties:
        return []
    pcts = []
    for i, p in enumerate(penalties):
        valid = [x for x in all_penalties_per_unit[i] if x < BIG_COST]
        if len(valid) <= 1:
            pcts.append(100.0)
        else:
            mn, mx = min(valid), max(valid)
            pcts.append(round((1 - (p - mn) / (mx - mn)) * 100, 1) if mx > mn else 100.0)
    return pcts


def _get_free_rooms_for_slot(weekday: str, start: str, end: str, week_type: str,
                              excluded_ids: set[int]) -> list:
    start_iso = _to_iso(start[11:16] if len(start) > 16 else start, weekday)
    end_iso = _to_iso(end[11:16] if len(end) > 16 else end, weekday)
    return [r for r in get_free_rooms(weekday, start_iso, end_iso, week_type)
            if r["id"] not in excluded_ids]


def strategy_random(lessons: list[dict], seed: int = 42) -> StrategyResult:
    rng = random.Random(seed)
    time_slots: dict[tuple, list[dict]] = {}
    for lesson in lessons:
        key = (lesson["weekday"], lesson["start"], lesson["end"], lesson["week_type"])
        time_slots.setdefault(key, []).append(lesson)

    all_penalties: list[int] = []
    all_match_pcts: list[float] = []
    all_penalties_per_unit: list[list[int]] = []
    n_assigned = 0
    n_unassigned = 0
    same_building_count = 0

    t0 = time.perf_counter()

    for slot_key, slot_lessons in time_slots.items():
        weekday, start, end, week_type = slot_key
        super_units = _build_super_units(slot_lessons)
        excluded_ids = set(u["room_id"] for u in super_units)
        free = _get_free_rooms_for_slot(weekday, start, end, week_type, excluded_ids)

        if not free:
            for u in super_units:
                n_unassigned += len(u["schedule_ids"])
            continue

        used_room_ids: set[int] = set()
        for unit in super_units:
            feasible = [r for r in free
                        if r["id"] not in used_room_ids
                        and r["capacity"] >= unit["students_count"]
                        and (not unit["needs_projector"] or r["has_projector"])
                        and (not unit["needs_computers"] or r["has_computers"])]
            all_penalties_for_unit = [_penalty_for_unit(unit, r) for r in free
                                      if r["id"] not in used_room_ids]
            all_penalties_per_unit.append(all_penalties_for_unit)

            if not feasible:
                n_unassigned += len(unit["schedule_ids"])
                continue

            room = rng.choice(feasible)
            used_room_ids.add(room["id"])
            p = _penalty_for_unit(unit, room)
            all_penalties.append(p)
            n_assigned += len(unit["schedule_ids"])
            if room["building"] == unit["room_building"]:
                same_building_count += len(unit["schedule_ids"])

    elapsed = (time.perf_counter() - t0) * 1000
    total = sum(all_penalties)
    n_total = len(all_penalties)
    match_pcts = _compute_match_pcts(all_penalties, all_penalties_per_unit)

    return StrategyResult(
        name="Random",
        total_penalty=total,
        avg_penalty=round(total / n_total, 1) if n_total else 0,
        n_assigned=n_assigned,
        n_unassigned=n_unassigned,
        elapsed_ms=round(elapsed, 2),
        penalties=all_penalties,
        same_building_pct=round(same_building_count / n_assigned * 100, 1) if n_assigned else 0,
        match_pcts=match_pcts,
    )


def strategy_greedy(lessons: list[dict]) -> StrategyResult:
    time_slots: dict[tuple, list[dict]] = {}
    for lesson in lessons:
        key = (lesson["weekday"], lesson["start"], lesson["end"], lesson["week_type"])
        time_slots.setdefault(key, []).append(lesson)

    all_penalties: list[int] = []
    all_match_pcts: list[float] = []
    all_penalties_per_unit: list[list[int]] = []
    n_assigned = 0
    n_unassigned = 0
    same_building_count = 0

    t0 = time.perf_counter()

    for slot_key, slot_lessons in time_slots.items():
        weekday, start, end, week_type = slot_key
        super_units = _build_super_units(slot_lessons)
        excluded_ids = set(u["room_id"] for u in super_units)
        free = _get_free_rooms_for_slot(weekday, start, end, week_type, excluded_ids)

        if not free:
            for u in super_units:
                n_unassigned += len(u["schedule_ids"])
            continue

        used_room_ids: set[int] = set()
        for unit in super_units:
            feasible = [(r, _penalty_for_unit(unit, r)) for r in free
                        if r["id"] not in used_room_ids
                        and r["capacity"] >= unit["students_count"]
                        and (not unit["needs_projector"] or r["has_projector"])
                        and (not unit["needs_computers"] or r["has_computers"])]
            all_penalties_for_unit = [_penalty_for_unit(unit, r) for r in free
                                      if r["id"] not in used_room_ids]
            all_penalties_per_unit.append(all_penalties_for_unit)

            if not feasible:
                n_unassigned += len(unit["schedule_ids"])
                continue

            feasible.sort(key=lambda x: x[1])
            room, p = feasible[0]
            used_room_ids.add(room["id"])
            all_penalties.append(p)
            n_assigned += len(unit["schedule_ids"])
            if room["building"] == unit["room_building"]:
                same_building_count += len(unit["schedule_ids"])

    elapsed = (time.perf_counter() - t0) * 1000
    total = sum(all_penalties)
    n_total = len(all_penalties)
    match_pcts = _compute_match_pcts(all_penalties, all_penalties_per_unit)

    return StrategyResult(
        name="Greedy (best-fit)",
        total_penalty=total,
        avg_penalty=round(total / n_total, 1) if n_total else 0,
        n_assigned=n_assigned,
        n_unassigned=n_unassigned,
        elapsed_ms=round(elapsed, 2),
        penalties=all_penalties,
        same_building_pct=round(same_building_count / n_assigned * 100, 1) if n_assigned else 0,
        match_pcts=match_pcts,
    )


def strategy_hungarian(lessons: list[dict]) -> StrategyResult:
    time_slots: dict[tuple, list[dict]] = {}
    for lesson in lessons:
        key = (lesson["weekday"], lesson["start"], lesson["end"], lesson["week_type"])
        time_slots.setdefault(key, []).append(lesson)

    all_penalties: list[int] = []
    all_match_pcts: list[float] = []
    n_assigned = 0
    n_unassigned = 0
    same_building_count = 0

    t0 = time.perf_counter()

    for slot_key, slot_lessons in time_slots.items():
        weekday, start, end, week_type = slot_key
        super_units = _build_super_units(slot_lessons)
        excluded_ids = set(u["room_id"] for u in super_units)
        free = _get_free_rooms_for_slot(weekday, start, end, week_type, excluded_ids)

        n = len(super_units)
        m = len(free)

        if m == 0:
            for u in super_units:
                n_unassigned += len(u["schedule_ids"])
            continue

        cost = _build_cost_matrix(super_units, free)
        row_indices, col_indices = linear_sum_assignment(cost)

        assigned_unit_indices: set[int] = set()
        for r_idx, c_idx in zip(row_indices, col_indices):
            p = int(cost[r_idx, c_idx])
            if p >= BIG_COST:
                continue
            assigned_unit_indices.add(r_idx)

            unit = super_units[r_idx]
            room = free[c_idx]
            all_penalties.append(p)
            n_assigned += len(unit["schedule_ids"])
            if room["building"] == unit["room_building"]:
                same_building_count += len(unit["schedule_ids"])

            valid_costs = cost[r_idx][cost[r_idx] < BIG_COST]
            if len(valid_costs) > 1:
                mn, mx = valid_costs.min(), valid_costs.max()
                match_pct = round((1 - (p - mn) / (mx - mn)) * 100, 1) if mx > mn else 100.0
            else:
                match_pct = 100.0
            all_match_pcts.append(match_pct)

        for i, u in enumerate(super_units):
            if i not in assigned_unit_indices:
                n_unassigned += len(u["schedule_ids"])

    elapsed = (time.perf_counter() - t0) * 1000
    total = sum(all_penalties)
    n_total = len(all_penalties)

    return StrategyResult(
        name="Hungarian (Kuhn-Munkres)",
        total_penalty=total,
        avg_penalty=round(total / n_total, 1) if n_total else 0,
        n_assigned=n_assigned,
        n_unassigned=n_unassigned,
        elapsed_ms=round(elapsed, 2),
        penalties=all_penalties,
        same_building_pct=round(same_building_count / n_assigned * 100, 1) if n_assigned else 0,
        match_pcts=all_match_pcts,
    )


def _print_algorithm_card(result: StrategyResult, n_total: int) -> None:
    print(f"  [{result.name}]")
    print(f"    Суммарный штраф:      {result.total_penalty}")
    print(f"    Средний штраф:        {result.avg_penalty:.1f}")
    print(f"    Медианный штраф:      {int(np.median(result.penalties)) if result.penalties else 0}")
    print(f"    Максимальный штраф:   {max(result.penalties, default=0)}")
    print(f"    Назначено:            {result.n_assigned} / {n_total}")
    print(f"    Не назначено:         {result.n_unassigned} ({round(result.n_unassigned / n_total * 100, 1) if n_total else 0}%)")
    print(f"    % в том же корпусе:   {result.same_building_pct:.1f}%")
    print(f"    Средний match%:       {round(float(np.mean(result.match_pcts)), 1) if result.match_pcts else 0}%")
    print(f"    Время:                {result.elapsed_ms:.2f} мс")
    print()


def _print_scenario_header(title: str, description: str, n_lessons: int) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print(f"  {description}")
    print(f"  Занятий для переноса: {n_lessons}")
    print("=" * 78)
    print()


def _print_results_detail(results: list[StrategyResult], n_total: int) -> None:
    for res in results:
        _print_algorithm_card(res, n_total)

    h = results[2]
    for res in results[:2]:
        if h.total_penalty > 0:
            d = round((res.total_penalty - h.total_penalty) / h.total_penalty * 100, 1)
            print(f"  >> Hungarian лучше {res.name} на {d}% по суммарному штрафу")
    print()


def _print_summary_table(all_results: list[tuple[str, str, list[StrategyResult]]]) -> None:
    print()
    print("=" * 78)
    print("  СВОДНАЯ ТАБЛИЦА")
    print("=" * 78)
    print()

    for title, _, results in all_results:
        n_total = results[0].n_assigned + results[0].n_unassigned
        short = title.split(". ", 1)[-1] if ". " in title else title
        print(f"  {short} ({n_total} зан.)")
        print(f"  {'':20s}  {'Random':>10s}  {'Greedy':>10s}  {'Hungarian':>10s}")
        print(f"  {'-'*54}")

        r, g, h = results
        pairs = [
            ("Суммарный штраф",  str(r.total_penalty),  str(g.total_penalty),  str(h.total_penalty)),
            ("Средний штраф",    f"{r.avg_penalty:.1f}", f"{g.avg_penalty:.1f}", f"{h.avg_penalty:.1f}"),
            ("Макс. штраф",      str(max(r.penalties, default=0)), str(max(g.penalties, default=0)), str(max(h.penalties, default=0))),
            ("Не назначено",     f"{r.n_unassigned}/{n_total}", f"{g.n_unassigned}/{n_total}", f"{h.n_unassigned}/{n_total}"),
            ("% в том же корп.", f"{r.same_building_pct:.1f}%", f"{g.same_building_pct:.1f}%", f"{h.same_building_pct:.1f}%"),
            ("Время (мс)",       f"{r.elapsed_ms:.1f}", f"{g.elapsed_ms:.1f}", f"{h.elapsed_ms:.1f}"),
        ]
        for label, rv, gv, hv in pairs:
            print(f"  {label:20s}  {rv:>10s}  {gv:>10s}  {hv:>10s}")

        if h.total_penalty > 0:
            delta = round((g.total_penalty - h.total_penalty) / h.total_penalty * 100, 1)
            print(f"  Hungarian > Greedy: +{delta}%")
        print()


def _get_n_lessons(building: str, weekday: str, week_type: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cnt = conn.execute("""
        SELECT COUNT(*) FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building = ? AND s.weekday = ? AND s.week_type = ?
    """, (building, weekday, week_type)).fetchone()[0]
    conn.close()
    return cnt


def _get_n_lessons_building(building: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cnt = conn.execute("""
        SELECT COUNT(*) FROM schedule s
        JOIN rooms r ON s.room_id = r.id
        WHERE r.building = ?
    """, (building,)).fetchone()[0]
    conn.close()
    return cnt


def run_scenario_1() -> tuple[str, str, list[StrategyResult]]:
    title = "1. Единичное занятие"
    desc = "Перенос 1 занятия из корпуса А, Понедельник, upper"
    lessons = _get_lessons_for_relocation("А", "Понедельник", "upper")
    if not lessons:
        return title, desc, []
    lessons = [lessons[0]]
    _print_scenario_header(title, desc, 1)
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, 1)
    return title, desc, results


def run_scenario_2() -> tuple[str, str, list[StrategyResult]]:
    title = "2. Малый массив (5 занятий)"
    desc = "Перенос 5 занятий из корпуса А, Понедельник, upper"
    lessons = _get_lessons_for_relocation("А", "Понедельник", "upper")
    if not lessons:
        return title, desc, []
    lessons = lessons[:5]
    _print_scenario_header(title, desc, len(lessons))
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, len(lessons))
    return title, desc, results


def run_scenario_3() -> tuple[str, str, list[StrategyResult]]:
    title = "3. Один корпус, один день"
    desc = "Перенос всех занятий из корпуса А, Понедельник, upper"
    lessons = _get_lessons_for_relocation("А", "Понедельник", "upper")
    _print_scenario_header(title, desc, len(lessons))
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, len(lessons))
    return title, desc, results


def run_scenario_4() -> tuple[str, str, list[StrategyResult]]:
    title = "4. Крупный корпус, один день"
    desc = "Перенос всех занятий из корпуса Л, Понедельник, upper"
    lessons = _get_lessons_for_relocation("Л", "Понедельник", "upper")
    _print_scenario_header(title, desc, len(lessons))
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, len(lessons))
    return title, desc, results


def run_scenario_5() -> tuple[str, str, list[StrategyResult]]:
    title = "5. Крупный корпус, один день, оба типа недель"
    desc = "Перенос всех занятий из корпуса Л, Понедельник (upper + lower)"
    lessons_u = _get_lessons_for_relocation("Л", "Понедельник", "upper")
    lessons_l = _get_lessons_for_relocation("Л", "Понедельник", "lower")
    lessons = lessons_u + lessons_l
    _print_scenario_header(title, desc, len(lessons))
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, len(lessons))
    return title, desc, results


def run_scenario_6() -> tuple[str, str, list[StrategyResult]]:
    title = "6. Крупный корпус, полная неделя"
    desc = "Перенос всех занятий из корпуса Л, все дни недели, upper"
    lessons = _get_lessons_for_relocation_building("Л", ["upper"])
    _print_scenario_header(title, desc, len(lessons))
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, len(lessons))
    return title, desc, results


def run_scenario_7() -> tuple[str, str, list[StrategyResult]]:
    title = "7. Закрытие корпуса Л на 2 недели"
    desc = "Перенос ВСЕХ занятий из корпуса Л (upper + lower, все дни) -- эквивалент закрытия на 2 недели"
    lessons = _get_lessons_for_relocation_building("Л", ["upper", "lower"])
    _print_scenario_header(title, desc, len(lessons))
    results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
    _print_results_detail(results, len(lessons))
    return title, desc, results


SCENARIOS = {
    1: run_scenario_1,
    2: run_scenario_2,
    3: run_scenario_3,
    4: run_scenario_4,
    5: run_scenario_5,
    6: run_scenario_6,
    7: run_scenario_7,
}


def run_all(scenario_ids: list[int] | None = None) -> None:
    if scenario_ids is None:
        scenario_ids = list(SCENARIOS.keys())

    print()
    print("#" * 78)
    print("  СРАВНЕНИЕ СТРАТЕГИЙ НАЗНАЧЕНИЯ АУДИТОРИЙ")
    print("  Random  |  Greedy (best-fit)  |  Hungarian (Kuhn-Munkres)")
    print("#" * 78)

    all_results: list[tuple[str, str, list[StrategyResult]]] = []

    for sid in scenario_ids:
        fn = SCENARIOS.get(sid)
        if fn is None:
            print(f"\n  Сценарий {sid} не найден (доступны: 1-7)")
            continue
        result = fn()
        if result[2]:
            all_results.append(result)

    if len(all_results) > 1:
        _print_summary_table(all_results)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Сравнение стратегий назначения аудиторий")
    parser.add_argument("--scenario", type=int, nargs="*", help="Номер(а) сценария (1-7). По умолчанию -- все")
    parser.add_argument("--custom", nargs=3, metavar=("BUILDING", "WEEKDAY", "WEEK_TYPE"),
                        help="Свой сценарий: А Понедельник upper")
    args = parser.parse_args()

    if args.custom:
        building, weekday, week_type = args.custom
        lessons = _get_lessons_for_relocation(building, weekday, week_type)
        if lessons:
            title = f"Custom: {building} / {weekday} / {week_type}"
            _print_scenario_header(title, f"Перенос всех занятий из {building}, {weekday}, {week_type}", len(lessons))
            results = [strategy_random(lessons), strategy_greedy(lessons), strategy_hungarian(lessons)]
            _print_results_detail(results, len(lessons))
        else:
            print(f"Нет занятий в {building} / {weekday} / {week_type}")
    elif args.scenario:
        run_all(args.scenario)
    else:
        run_all()
