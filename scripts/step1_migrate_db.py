"""
Шаг 1. Модификация схемы БД и генерация недостающих данных.

Ключевой принцип: реальное расписание уже корректно.
Параметры аудиторий выводятся из того, что в них ДЕЙСТВИТЕЛЬНО происходит.
Никаких конфликтов «занятие требует X, а в аудитории нет X» быть не может.

Порядок:
1. lessons — needs_projector / needs_computers по типу занятия.
2. groups — students_count (реалистичные 15-35).
3. rooms — capacity и оборудование выводятся из пересекающихся занятий и групп.
"""

import sqlite3
import random
import re
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..\\data\\schedule.db")
random.seed(42)


# ──────────────────────────────────────────────
# 1. Схема
# ──────────────────────────────────────────────

def alter_schema(conn: sqlite3.Connection):
    cursor = conn.cursor()

    for col, ctype in [("capacity", "INTEGER"), ("has_projector", "BOOLEAN"), ("has_computers", "BOOLEAN")]:
        if col not in _cols(conn, "rooms"):
            cursor.execute(f"ALTER TABLE rooms ADD COLUMN {col} {ctype}")
            print(f"  [rooms] +{col}")

    if "students_count" not in _cols(conn, "groups"):
        cursor.execute("ALTER TABLE groups ADD COLUMN students_count INTEGER")
        print("  [groups] +students_count")

    for col, ctype in [("needs_projector", "BOOLEAN"), ("needs_computers", "BOOLEAN")]:
        if col not in _cols(conn, "lessons"):
            cursor.execute(f"ALTER TABLE lessons ADD COLUMN {col} {ctype}")
            print(f"  [lessons] +{col}")

    conn.commit()


def _cols(conn, table):
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cursor.fetchall()}


# ──────────────────────────────────────────────
# 2. Lessons — оборудование по типу занятия
# ──────────────────────────────────────────────

def fill_lessons(conn: sqlite3.Connection):
    """
    Лекционные  → проектор (преподаватель показывает слайды).
    Лабораторные → проектор + компьютеры (преподаватель показывает + студенты работают).
    Практические → чаще проектор, иногда компьютеры.

    Исключения: физкультура не требует ни проектора, ни компьютеров.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, lesson_type FROM lessons")

    updates = []
    for lid, title, ltype in cursor.fetchall():
        title_lower = title.lower()

        # Физкультура — в спортзале, никакого оборудования
        if "физическ" in title_lower or "спорт" in title_lower:
            proj, comp = 0, 0
        elif ltype == "Лекционные":
            proj, comp = 1, 0
        elif ltype == "Лабораторные":
            proj, comp = 1, 1
        elif ltype == "Практические":
            proj = random.choice([1, 1, 0])   # ~67%
            comp = random.choice([1, 0, 0, 0]) # ~25%
        else:
            proj, comp = 0, 0
        updates.append((proj, comp, lid))

    cursor.executemany(
        "UPDATE lessons SET needs_projector = ?, needs_computers = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    print(f"  [lessons] Обновлено {len(updates)} записей")


# ──────────────────────────────────────────────
# 3. Groups — размер группы
# ──────────────────────────────────────────────

def fill_groups(conn: sqlite3.Connection):
    """15-30 стандарт, 20-35 для старших курсов (24, 25)."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM groups")

    updates = []
    for gid, name in cursor.fetchall():
        if re.search(r"-(24|25)-", name):
            n = random.randint(20, 35)
        else:
            n = random.randint(15, 30)
        updates.append((n, gid))

    cursor.executemany("UPDATE groups SET students_count = ? WHERE id = ?", updates)
    conn.commit()
    print(f"  [groups] Обновлено {len(updates)} записей")


# ──────────────────────────────────────────────
# 4. Rooms — вывод из реального расписания
# ──────────────────────────────────────────────

def fill_rooms(conn: sqlite3.Connection):
    """
    Для каждой аудитории:
    - capacity = max(students_count групп, которые туда ходят) + случайный запас 0-10
    - has_projector = 1 если хоть одно занятие там требует проектор
    - has_computers = 1 если хоть одно занятие там требует компьютеры

    Гарантируется: ни одно существующее занятие не окажется в неподходящей аудитории.
    """
    cursor = conn.cursor()

    # Максимальный размер группы для каждой аудитории
    cursor.execute("""
        SELECT s.room_id, MAX(g.students_count) as max_grp
        FROM schedule s
        JOIN groups g ON s.group_id = g.id
        GROUP BY s.room_id
    """)
    max_per_room = dict(cursor.fetchall())

    # Нужно ли оборудование в каждой аудитории (OR по всем занятиям)
    cursor.execute("""
        SELECT s.room_id,
               MAX(l.needs_projector) as need_proj,
               MAX(l.needs_computers) as need_comp
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        GROUP BY s.room_id
    """)
    equip_per_room = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}

    # Обновляем все аудитории
    cursor.execute("SELECT id, name, building FROM rooms")
    updates = []
    for room_id, name, building in cursor.fetchall():

        # Специальные случаи
        if building == "Онлайн":
            # Виртуальная аудитория — принимает любые занятия
            updates.append((999, 1, 1, room_id))
            continue
        if building == "Спортивный комплекс Беляево":
            updates.append((random.randint(100, 200), 0, 0, room_id))
            continue
        if building == "Каф. ИЯКТ":
            base = max_per_room.get(room_id, 20)
            cap = base + random.randint(0, 5)
            updates.append((cap, 1, 0, room_id))
            continue

        # Обычные аудитории — вывод из расписания
        if room_id in max_per_room:
            base_cap = max_per_room[room_id]
            cap = base_cap + random.randint(0, 10)  # минимальный запас
        else:
            # Аудитория не используется в расписании — дефолт по корпусу
            if building == "Г":
                cap, _proj, _comp = random.randint(25, 35), 1, 1
            elif building in ("А", "Л"):
                cap, _proj, _comp = random.randint(30, 60), 1, 0
            else:
                cap, _proj, _comp = random.randint(20, 40), 0, 0
            updates.append((cap, _proj, _comp, room_id))
            continue

        proj, comp = equip_per_room.get(room_id, (0, 0))
        updates.append((cap, proj, comp, room_id))

    cursor.executemany(
        "UPDATE rooms SET capacity = ?, has_projector = ?, has_computers = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    print(f"  [rooms] Обновлено {len(updates)} записей")


# ──────────────────────────────────────────────
# 5. Проверка: НУЛЕВОЙ конфликт
# ──────────────────────────────────────────────

def verify_no_conflicts(conn: sqlite3.Connection):
    """Проверяет, что ВСЕ существующие занятия помещаются в свои аудитории."""
    cursor = conn.cursor()

    # Конфликты по вместимости
    cursor.execute("""
        SELECT s.id, g.name, g.students_count, r.name, r.capacity
        FROM schedule s
        JOIN groups g ON s.group_id = g.id
        JOIN rooms r ON s.room_id = r.id
        WHERE g.students_count > r.capacity
    """)
    cap_conflicts = cursor.fetchall()

    # Конфликты по оборудованию
    cursor.execute("""
        SELECT s.id, l.title, l.lesson_type,
               l.needs_projector, r.has_projector,
               l.needs_computers,  r.has_computers,
               r.name
        FROM schedule s
        JOIN lessons l ON s.lesson_id = l.id
        JOIN rooms r ON s.room_id = r.id
        WHERE (l.needs_projector AND NOT r.has_projector)
           OR (l.needs_computers  AND NOT r.has_computers)
    """)
    equip_conflicts = cursor.fetchall()

    print("\n=== VERIFICATION ===")
    if cap_conflicts:
        print(f"\n  ⚠ КОНФЛИКТЫ ВМЕСТИМОСТИ: {len(cap_conflicts)}")
        for c in cap_conflicts[:5]:
            print(f"    schedule#{c[0]} | группа {c[1]} ({c[2]} студ.) → {c[3]} (cap={c[4]})")
    else:
        print("\n  ✓ Вместимость: 0 конфликтов")

    if equip_conflicts:
        print(f"\n  ⚠ КОНФЛИКТЫ ОБОРУДОВАНИЯ: {len(equip_conflicts)}")
        for c in equip_conflicts[:5]:
            print(f"    schedule#{c[0]} | {c[1]} ({c[2]}) → {c[7]} | "
                  f"proj needs={c[3]} has={c[4]}, comp needs={c[5]} has={c[6]}")
    else:
        print("  ✓ Оборудование: 0 конфликтов")

    # Сводка
    cursor.execute("SELECT COUNT(*) FROM schedule")
    total = cursor.fetchone()[0]
    print(f"\n  Всего записей в расписании: {total}")
    print(f"  Конфликтов: {len(cap_conflicts) + len(equip_conflicts)}")


def verify_stats(conn: sqlite3.Connection):
    """Статистика для наглядности."""
    cursor = conn.cursor()

    print("\n--- Rooms by building ---")
    cursor.execute("""
        SELECT building, COUNT(*) as cnt,
               MIN(capacity), MAX(capacity), ROUND(AVG(capacity)),
               SUM(has_projector), SUM(has_computers)
        FROM rooms WHERE building NOT IN ('Онлайн')
        GROUP BY building
    """)
    for r in cursor.fetchall():
        print(f"  {r[0]:30s} | n={r[1]} | cap=[{r[2]}..{r[3]}] avg={r[4]} | proj={r[5]} | comp={r[6]}")

    print("\n--- Groups ---")
    r = cursor.execute("SELECT MIN(students_count), MAX(students_count), ROUND(AVG(students_count)) FROM groups").fetchone()
    print(f"  students=[{r[0]}..{r[1]}], avg={r[2]}")

    print("\n--- Lessons ---")
    for r in cursor.execute("""
        SELECT lesson_type, COUNT(*),
               SUM(needs_projector), SUM(needs_computers)
        FROM lessons GROUP BY lesson_type
    """).fetchall():
        print(f"  {r[0]:20s} | n={r[1]} | proj={r[2]} | comp={r[3]}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    if not os.path.exists(DB_PATH):
        print(f"ОШИБКА: БД не найдена: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    print(f"БД: {DB_PATH}")

    print("\n1. Схема...");     alter_schema(conn)
    print("\n2. Lessons...");   fill_lessons(conn)
    print("\n3. Groups...");    fill_groups(conn)
    print("\n4. Rooms...");     fill_rooms(conn)
    print("\n5. Проверка...");  verify_no_conflicts(conn)
    verify_stats(conn)

    conn.close()
    print("\nГотово!")


if __name__ == "__main__":
    main()
