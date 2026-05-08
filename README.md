# Корректировка аудиторного расписания

Автоматизированная система корректировки аудиторного расписания вуза с использованием венгерского алгоритма оптимизации.

## Структура проекта

```
diploma/
├── run.bat                  # Точка входа — двойной клик для запуска
├── .gitignore
│
├── src/                     # Исходный код приложения
│   ├── __init__.py
│   ├── app.py               # Streamlit UI (4 страницы: Incidents, Booking, Schedule, Management)
│   ├── search_engine.py     # Поиск свободных аудиторий, информация о занятиях
│   ├── optimization.py      # Массовое перераспределение (венгерский алгоритм)
│   └── scoring.py           # Функция стоимости, штрафы, % пригодности
│
├── scripts/                 # Утилиты и миграции
│   ├── add_booking_tables.py    # Создание таблиц бронирования
│   ├── migrate_dates.py         # Миграция: weekday+week_type → booking_date
│   ├── step1_migrate_db.py      # Первичная миграция БД
│   ├── fix_lecture_capacity.py  # Фикс вместимости лекций
│   └── inspect_db.py            # Просмотр содержимого БД
│
├── data/                    # Данные
│   └── schedule.db              # SQLite база данных расписания
│
├── tests/                   # Тесты
│   ├── _test_*.py               # Unit-тесты модулей
│   └── _check_*.py              # Проверочные скрипты
│
└── example.png              # Скриншот интерфейса
```

## Быстрый запуск

### Вариант 1: run.bat (Windows)
```
Двойной клик по run.bat
```

### Вариант 2: вручную
```bash
# 1. Создать виртуальное окружение (если нет)
python -m venv .venv

# 2. Активировать
.venv\Scripts\activate

# 3. Установить зависимости
pip install streamlit scipy pandas numpy

# 4. Запустить приложение
streamlit run src/app.py --server.headless true --server.port 8502
```

Приложение откроется по адресу: **http://localhost:8502**

Проверка: `curl http://localhost:8502/healthz` → должен вернуть `ok`.

---

## Архитектура: от данных до результата

### Пайплайн работы системы

```
┌─────────────────────────────────────────────────────────────────┐
│                        1. ДАННЫЕ (БД)                           │
│                                                                 │
│  schedule.db (SQLite)                                           │
│  ├── rooms          (~115 аудиторий: название, корпус, этаж,    │
│  │                    вместимость, проектор, компьютеры)         │
│  ├── groups         (156 групп: название, кол-во студентов)     │
│  ├── lessons        (820 занятий: предмет, тип, оборудование)   │
│  ├── schedule       (3502+ записей: расписание групп)           │
│  ├── transfers      (переносы аудиторий с привязкой к дате)     │
│  └── event_bookings (бронирования для мероприятий)              │
│                                                                 │
│  Ключевое поле: booking_date — привязка к конкретной дате,      │
│  а не к абстрактному "понедельник чётной недели"                │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  2. SEARCH ENGINE   │
                    │  search_engine.py   │
                    └──────────┬──────────┘
                               │
    Функции:
    • get_free_rooms(weekday, start, end, week_type)
      → SQL-запрос: все аудитории, НЕ занятые в этот слот
      → Исключаются: "Онлайн", "Каф. ИЯКТ", "Спорткомплекс Беляево"

    • get_lesson_info(schedule_id)
      → JOIN schedule + lessons + groups + rooms
      → Возвращает: предмет, тип, группу, студентов, оборудование,
        original_room, weekday, start, end, week_type, lesson_id

    • find_room_for_event(capacity, projector, computers, ...)
      → get_free_rooms + filter_rooms → топ-N по мин. избытку мест

    • filter_rooms(rooms, students, projector, computers)
      → Отсеивает по hard-контрэйнтам (вместимость, оборудование)

                               │
                    ┌──────────▼──────────┐
                    │   3. SCORING        │
                    │   scoring.py        │
                    └──────────┬──────────┘
                               │
    Функция calculate_penalty():
    ┌─────────────────────────────────────────────────────────────┐
    │  penalty = 0                                                │
    │                                                             │
    │  if building != original_building:  penalty += 100          │
    │  penalty += abs(floor - original_floor) * 5                 │
    │  penalty += max(0, capacity - students) * 1    # лишние места│
    │  if needs_computers and not has_computers: penalty += 10    │
    │  if needs_projector and not has_projector:   penalty += 5   │
    │                                                             │
    │  match_percent = max(0, 100 - penalty)                      │
    └─────────────────────────────────────────────────────────────┘

    ScoredRoom = {room_id, name, building, floor, capacity,
                  has_projector, has_computers, penalty, match_percent}

                               │
                    ┌──────────▼──────────┐
                    │  4. OPTIMIZATION    │
                    │  optimization.py    │
                    └──────────┬──────────┘
                               │
    mass_reallocate(schedule_ids):

    Шаг 1: Собрать информацию о всех занятиях (get_lesson_info)

    Шаг 2: Сгруппировать по временным слотам (weekday, start, end, week_type)

    Шаг 3: Внутри каждого слота — группировка по lesson_id:
           • Обычное занятие = 1 группа → 1 аудитория
           • Лекция = N групп → СУММА студентов → 1 общая аудитория

    Шаг 4: Для каждого "супер-урока":
           a) Найти свободные аудитории (get_free_rooms)
           b) Построить матрицу стоимостей N×M
              cost[i][j] = calculate_penalty(lesson_i, room_j)
              Если room не подходит → cost = 10^9 (BIG_COST)
           c) Венгерский алгоритм (scipy.linear_sum_assignment)
              → Минимальная суммарная стоимость назначений
           d) Построить ScoredRoom для каждой пары

    Шаг 5: Вернуть MassReallocationResult:
           • assignments: {schedule_id: ScoredRoom}
           • unassigned: [schedule_id, ...] — кому не хватило
           • total_penalty, avg_penalty, avg_match_percent

                               │
                    ┌──────────▼──────────┐
                    │  5. STREAMLET UI    │
                    │  app.py             │
                    └──────────┬──────────┘
                               │
    4 страницы:

    📋 Инциденты (Incidents)
    ├── Выбор проблемной аудитории и периода
    ├── Поиск всех занятий в этой аудитории за период
    ├── Генерация замен (mass_reallocate)
    └── Таблица результатов + сохранение в БД

    📅 Бронирование (Booking)
    ├── Создание мероприятия (название, организатор, кол-во человек)
    ├── Выбор временного слота
    ├── Подбор аудитори (find_room_for_event)
    └── Сохранение бронирования

    🗓 Расписание (Schedule)
    ├── Фильтры: корпус, день, неделя
    └── Визуальная таблица расписания с цветовым кодированием:
        🔵 Занятие | 🟢 Перенесено сюда | 🔴 Перенесено отсюда | 🟡 Мероприятие

    ⚙️ Управление (Management)
    ├── Переносы: просмотр, фильтрация, удаление
    │   └── Лекции группируются в одну строку (все группы вместе)
    └── Бронирования: просмотр, фильтрация, отмена

---

## Схема базы данных

### rooms
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | ID аудитории |
| name | TEXT | Название (А-308) |
| building | TEXT | Корпус (А, Б, В, Г...) |
| floor | INTEGER | Этаж |
| capacity | INTEGER | Вместимость |
| has_projector | BOOLEAN | Проектор |
| has_computers | BOOLEAN | Компьютеры |

### groups
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | ID группы |
| name | TEXT | Название (БИВТ-25-5) |
| students_count | INTEGER | Количество студентов |

### lessons
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | ID занятия |
| title | TEXT | Предмет |
| lesson_type | TEXT | Лекционные/Практические/Лабораторные |
| teacher | TEXT | Преподаватель |
| needs_projector | BOOLEAN | Нужен проектор |
| needs_computers | BOOLEAN | Нужны компьютеры |

### schedule
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | ID записи |
| lesson_id | INTEGER FK → lessons | Занятие |
| group_id | INTEGER FK → groups | Группа |
| room_id | INTEGER FK → rooms | Аудитория |
| weekday | TEXT | День недели |
| start | TEXT | Начало (HH:MM:SS) |
| end | TEXT | Конец (HH:MM:SS) |
| week_type | TEXT | upper (чётная) / lower (нечётная) |

### transfers
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | ID переноса |
| lesson_id | INTEGER FK | Занятие |
| group_id | INTEGER FK | Группа |
| old_room_id | INTEGER FK | Была |
| new_room_id | INTEGER FK | Стала |
| booking_date | TEXT | Дата (YYYY-MM-DD) |
| weekday | TEXT | День недели |
| start | TEXT | Начало |
| end | TEXT | Конец |
| week_type | TEXT | Тип недели |
| created_at | TEXT | Время создания |

### event_bookings
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER PK | ID бронирования |
| room_id | INTEGER FK | Аудитория |
| event_name | TEXT | Название мероприятия |
| organizer | TEXT | Организатор |
| attendees_count | INTEGER | Кол-во участников |
| needs_projector | BOOLEAN | Нужен проектор |
| needs_computers | BOOLEAN | Нужны компьютеры |
| booking_date | TEXT | Дата |
| start | TEXT | Начало |
| end | TEXT | Конец |
| weekday | TEXT | День недели |
| week_type | TEXT | Тип недели |

---

## Ключевые принципы

### Типы недель
Определяются по номеру недели относительно BASE_MONDAY = 2026-01-12:
- **upper** (чётная) — номер недели чётный
- **lower** (нечётная) — номер недели нечётный

### Временные слоты (7 пар)
| Пара | Время |
|------|-------|
| 1 | 09:00–10:35 |
| 2 | 10:50–12:25 |
| 3 | 12:40–14:15 |
| 4 | 14:30–16:05 |
| 5 | 16:15–17:50 |
| 6 | 18:00–19:25 |
| 7 | 19:35–21:00 |

### Лекции = "супер-уроки"
Если несколько групп имеют одинаковый `lesson_id` в одном временном слоте:
- Суммируются студенты: `total = sum(group.students_count)`
- Объединяются требования: проектор = True если нужен хотя бы одной группе
- Подбирается **одна** аудитория на всех
- Все `schedule_id` получают одну и ту же аудитору

### Исключённые корпуса
Не участвуют в поиске и бронировании:
- `Онлайн`
- `Каф. ИЯКТ`
- `Спортивный комплекс Беляево`

---

## Тестирование

```bash
# Запустить все тесты
cd tests
for %f in (_test_*.py) do python %f

# Проверить синтаксис
python -m py_compile src\app.py src\search_engine.py src\optimization.py src\scoring.py
```

---

## Зависимости

| Пакет | Версия | Назначение |
|-------|--------|------------|
| streamlit | >=1.30 | Веб-интерфейс |
| scipy | >=1.11 | Венгерский алгоритм (linear_sum_assignment) |
| pandas | >=2.0 | Таблицы в UI |
| numpy | >=1.24 | Матрица стоимостей |
| sqlite3 | built-in | База данных |

```bash
pip install streamlit scipy pandas numpy
```
