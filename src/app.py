import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, timedelta, datetime as dt

from src.search_engine import get_lesson_info, find_room_for_event
from src.optimization import mass_reallocate
from src.stats import pc_utilization, capacity_demand, transfer_destinations, fund_summary_with_transfers
from src.cancellation import (
    ensure_cancellations_table,
    preview_cancel_by_teacher,
    preview_cancel_by_discipline,
    preview_cancel_single,
    apply_cancels,
    get_cancellations,
    get_active_cancellations_for_date,
    get_restored_for_date,
    find_restore_slots,
    restore_lesson,
    mass_restore,
    mass_restore_preview,
    delete_cancellation,
    get_all_teachers,
    get_all_disciplines,
    CancelPreview,
    RestoreSlot,
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

if not os.path.exists(DB_PATH):
    st.set_page_config(page_title="Корректировка расписания", layout="wide")
    st.error("База данных не найдена: `data/schedule.db`")
    st.markdown("**Создайте БД одним из способов:**\n\n"
                "1. Двойной клик `run.bat` — автоматически\n\n"
                "2. Вручную:\n```\n"
                "pip install -r requirements.txt\n"
                "python pipeline/build_db.py\n```\n\n"
                "Скрипт скачает расписание с API `schedule.misis.club` (~2 мин).")
    st.stop()

st.set_page_config(
    page_title="Корректировка расписания",
    page_icon=None, layout="wide",
    initial_sidebar_state="expanded",
)

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WD_R = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}

SLOTS = [
    {"name": "1-я пара", "start": "09:00", "end": "10:35"},
    {"name": "2-я пара", "start": "10:50", "end": "12:25"},
    {"name": "3-я пара", "start": "12:40", "end": "14:15"},
    {"name": "4-я пара", "start": "14:30", "end": "16:05"},
    {"name": "5-я пара", "start": "16:20", "end": "17:55"},
    {"name": "6-я пара", "start": "18:00", "end": "19:25"},
    {"name": "7-я пара", "start": "19:35", "end": "21:00"},
]

BASE_MONDAY = date(2026, 1, 12)


def t2m(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def d2wt(d):
    if isinstance(d, dt):
        d = d.date()
    elif not isinstance(d, date):
        d = date(int(str(d)[:4]), int(str(d)[5:7]), int(str(d)[8:10]))
    diff = (d - BASE_MONDAY).days
    return "upper" if (diff // 7) % 2 == 0 else "lower"


def d2wd(d):
    if isinstance(d, dt):
        d = d.date()
    elif not isinstance(d, date):
        d = date(int(str(d)[:4]), int(str(d)[5:7]), int(str(d)[8:10]))
    return WD_R.get(d.weekday(), "")


def to_iso(t, d=None):
    dt = str(d) if d else "2026-01-12"
    return f"{dt}T{t}:00+03:00"


def t_from_iso(s):
    return s[11:16] if s else ""


def slot_label(start_str, end_str):
    for sl in SLOTS:
        if sl["start"] == start_str and sl["end"] == end_str:
            return f"{sl['start']}–{sl['end']} ({sl['name']})"
    return f"{start_str}–{end_str}"


def gc():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    c = gc()
    cur = c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        schedule_id INT, old_room_id INT, new_room_id INT,
        weekday TEXT, start TEXT, end TEXT, week_type TEXT,
        lesson_id INT, group_id INT, reason TEXT,
        booking_date TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS event_bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        room_id INT, weekday TEXT, start TEXT, end TEXT, week_type TEXT,
        event_name TEXT, organizer TEXT, attendees_count INT,
        needs_projector BOOLEAN, needs_computers BOOLEAN,
        booking_date TEXT)""")
    c.commit()
    c.close()


ensure_tables()
ensure_cancellations_table()


def get_rooms():
    c = gc()
    r = c.execute("SELECT id,name,building,floor,capacity,has_projector,has_computers FROM rooms WHERE building NOT IN ('Онлайн','Каф. ИЯКТ','Спортивный комплекс Беляево') ORDER BY building,name").fetchall()
    c.close()
    return r


def get_buildings():
    c = gc()
    r = c.execute("SELECT DISTINCT building FROM rooms WHERE building NOT IN ('Онлайн','Каф. ИЯКТ','Спортивный комплекс Беляево') ORDER BY building").fetchall()
    c.close()
    return [x[0] for x in r]


def get_transferred_schedule_ids():
    c = gc()
    rows = c.execute("SELECT DISTINCT schedule_id FROM transfers").fetchall()
    c.close()
    return {r["schedule_id"] for r in rows}


def get_affected(room_ids, sd, ed):
    """Найти занятия в аудиториях за период КОНКРЕТНЫХ дат."""
    if not room_ids or not sd or not ed:
        return []
    transferred_sids = get_transferred_schedule_ids()
    c = gc()
    ph = ",".join("?" for _ in room_ids)
    dates = []
    d = sd
    while d <= ed:
        dates.append((d2wd(d), d2wt(d), d))
        d += timedelta(days=1)
    cond = " OR ".join("(s.weekday=? AND s.week_type=?)" for _ in dates)
    q = f"""SELECT s.id,r.name as room_name,s.weekday,s.start,s.end,s.week_type,
            l.id as lesson_id,l.title as lesson_title,l.lesson_type,
            l.needs_projector,l.needs_computers,
            g.id as group_id,g.name as group_name,g.students_count
        FROM schedule s JOIN rooms r ON s.room_id=r.id
        JOIN lessons l ON s.lesson_id=l.id JOIN groups g ON s.group_id=g.id
        WHERE r.id IN ({ph}) AND ({cond}) ORDER BY s.start,r.name"""
    params = list(room_ids)
    for wd, wt, _ in dates:
        params.extend([wd, wt])
    rows = c.execute(q, params).fetchall()
    c.close()
    result = []
    for r in rows:
        if r["id"] in transferred_sids:
            continue
        for wd, wt, d in dates:
            if r["weekday"] == wd and r["week_type"] == wt:
                result.append({**dict(r), "booking_date": str(d)})
                break
    return result


def get_sched_for_date(sel_date):
    """Занятия для конкретной даты."""
    wd = d2wd(sel_date)
    wt = d2wt(sel_date)
    c = gc()
    rows = c.execute("""
        SELECT s.id,s.room_id,r.name as room_name,r.building,r.floor,
               l.title as lesson_title,l.lesson_type,g.name as group_name,
               substr(s.start,12,5) as st,substr(s.end,12,5) as et
        FROM schedule s JOIN rooms r ON s.room_id=r.id
        JOIN lessons l ON s.lesson_id=l.id JOIN groups g ON s.group_id=g.id
        WHERE s.weekday=? AND s.week_type=? ORDER BY r.name,s.start
    """, (wd, wt)).fetchall()
    c.close()
    g = {}
    for r in rows:
        k = (r["room_id"], r["st"], r["et"])
        if k not in g:
            g[k] = {
                "room_id": r["room_id"], "room_name": r["room_name"],
                "building": r["building"], "floor": r["floor"],
                "lesson_title": r["lesson_title"], "lesson_type": r["lesson_type"],
                "sids": [], "groups": [], "start": r["st"], "end": r["et"],
            }
        g[k]["sids"].append(r["id"])
        g[k]["groups"].append(r["group_name"])
    out = []
    for v in g.values():
        v["gd"] = ", ".join(sorted(set(v["groups"]))) if len(v["groups"]) > 1 else v["groups"][0]
        out.append(v)
    return out, wd, wt


def get_transfers_for_date(sel_date):
    """Переносы для КОНКРЕТНОЙ даты."""
    c = gc()
    r = c.execute("""
        SELECT t.id as tid,t.schedule_id,t.booking_date,r1.name as old_room,r2.name as new_room,
               r2.id as new_room_id,l.title as lesson_title,l.lesson_type,g.name as group_name,
               substr(t.start,12,5) as st,substr(t.end,12,5) as et
        FROM transfers t JOIN rooms r1 ON t.old_room_id=r1.id
        JOIN rooms r2 ON t.new_room_id=r2.id
        JOIN lessons l ON t.lesson_id=l.id JOIN groups g ON t.group_id=g.id
        WHERE t.booking_date=?
    """, (str(sel_date),)).fetchall()
    c.close()
    return r


def get_bookings_for_date(room_id, sel_date):
    """Бронирования для аудитории на КОНКРЕТНУЮ дату."""
    c = gc()
    r = c.execute("""
        SELECT eb.id as bid,eb.event_name,eb.organizer,eb.attendees_count,eb.booking_date,
               substr(eb.start,12,5) as st,substr(eb.end,12,5) as et
        FROM event_bookings eb WHERE eb.room_id=? AND eb.booking_date=?
    """, (room_id, str(sel_date))).fetchall()
    c.close()
    return r


def check_booking_conflict(room_id, sel_date, s, e, exclude_bid=None):
    """Проверить конфликт по КОНКРЕТНОЙ дате (учитывает schedule, transfers, event_bookings)."""
    c = gc()
    q = """SELECT COUNT(*) as cnt FROM event_bookings
           WHERE room_id=? AND booking_date=?
           AND substr(start,12,5) < ? AND substr(end,12,5) > ?"""
    params = [room_id, str(sel_date), e, s]
    if exclude_bid:
        q += " AND id != ?"
        params.append(exclude_bid)
    r = c.execute(q, params).fetchone()
    if r["cnt"] > 0:
        c.close()
        return True
    wd = d2wd(sel_date)
    wt = d2wt(sel_date)
    r2 = c.execute("""
        SELECT COUNT(*) as cnt FROM schedule
        WHERE room_id=? AND weekday=? AND week_type=?
        AND substr(start,12,5) < ? AND substr(end,12,5) > ?
        AND id NOT IN (
            SELECT t.schedule_id FROM transfers t
            WHERE t.booking_date=? AND t.old_room_id=?
        )
    """, (room_id, wd, wt, e, s, str(sel_date), room_id)).fetchone()
    if r2["cnt"] > 0:
        c.close()
        return True
    r3 = c.execute("""
        SELECT COUNT(*) as cnt FROM transfers
        WHERE new_room_id=? AND booking_date=?
        AND substr(start,12,5) < ? AND substr(end,12,5) > ?
    """, (room_id, str(sel_date), e, s)).fetchone()
    c.close()
    return r3["cnt"] > 0


def save_transfers(assignments, date_map, sd, ed):
    """Сохранить переносы с booking_date.
    Для каждого assignment создаём запись для КАЖДОЙ даты в диапазоне [sd, ed],
    у которой совпадает (weekday, week_type).
    date_map: dict schedule_id -> booking_date (первая найденная дата)
    """
    # Собираем все даты в диапазоне, сгруппированные по (weekday, week_type)
    date_groups = {}  # (weekday, week_type) -> [date, ...]
    d = sd
    while d <= ed:
        key = (d2wd(d), d2wt(d))
        date_groups.setdefault(key, []).append(d)
        d += timedelta(days=1)

    c = gc()
    saved_count = 0
    for sid, sr in assignments.items():
        info = get_lesson_info(sid)
        key = (info["weekday"], info["week_type"])
        dates_for_this = date_groups.get(key, [])
        for bdate in dates_for_this:
            c.execute(
                "INSERT INTO transfers(schedule_id,old_room_id,new_room_id,weekday,start,end,week_type,lesson_id,group_id,reason,booking_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (sid, info["room_id"], sr.room_id, info["weekday"], info["start"], info["end"],
                 info["week_type"], info["lesson_id"], info["group_id"], "Инцидент", str(bdate)),
            )
            saved_count += 1
    c.commit()
    c.close()
    return saved_count


def save_booking(room, name, org, att, sel_date, s, e, p, co):
    wd = d2wd(sel_date)
    wt = d2wt(sel_date)
    c = gc()
    c.execute(
        "INSERT INTO event_bookings(room_id,weekday,start,end,week_type,event_name,organizer,attendees_count,needs_projector,needs_computers,booking_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (room["id"], wd, to_iso(s, sel_date), to_iso(e, sel_date), wt, name, org, att, p, co, str(sel_date)),
    )
    c.commit()
    c.close()


def del_transfer(tid):
    c = gc()
    c.execute("DELETE FROM transfers WHERE id=?", (tid,))
    c.commit()
    c.close()


def del_booking(bid):
    c = gc()
    c.execute("DELETE FROM event_bookings WHERE id=?", (bid,))
    c.commit()
    c.close()


@st.dialog("Подтверждение бронирования")
def _show_booking_confirm_dialog(data):
    room = data["room"]
    par = data["par"]
    rm_name = room["name"]
    rm_bld = room["building"]
    rm_fl = room["floor"]
    rm_cap = room["capacity"]
    p_name = par.get("n", "?")
    p_org = par.get("o", "?")
    p_att = par.get("c", "?")
    p_date = par.get("date", "?")
    p_s = par.get("s", "?")
    p_e = par.get("e", "?")
    p_wd = par.get("wd", "")
    p_wt = par.get("wt", "")
    wt_label = "верхняя" if p_wt == "upper" else "нижняя" if p_wt else ""

    st.write(f"**Аудитория:** {rm_name} (корп. {rm_bld}, эт. {rm_fl})")
    st.write(f"**Вместимость:** {rm_cap} мест")
    eq = []
    if room.get("has_projector"):
        eq.append("Проектор")
    if room.get("has_computers"):
        eq.append("Компьютеры")
    st.write(f"**Оборудование:** {' | '.join(eq) if eq else '—'}")
    st.divider()
    st.write(f"**Мероприятие:** {p_name}")
    st.write(f"**Организатор:** {p_org}")
    st.write(f"**Участников:** {p_att}")
    st.write(f"**Дата:** {p_date} ({p_wd}, {wt_label} неделя)")
    st.write(f"**Время:** {p_s}–{p_e}")

    need_proj = par.get("p", False)
    need_comp = par.get("co", False)
    if need_proj and not room.get("has_projector"):
        st.warning("Внимание: мероприятию требуется проектор, но в аудитории его нет!")
    if need_comp and not room.get("has_computers"):
        st.warning("Внимание: мероприятию требуются компьютеры, но в аудитории их нет!")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Подтвердить", type="primary", use_container_width=True):
            save_booking(
                room, p_name, p_org, p_att, p_date,
                p_s, p_e, need_proj, need_comp,
            )
            st.session_state["evd"] = rm_name
            st.session_state["evt"] = f"{p_date} {p_s}–{p_e}"
            st.session_state["evr"] = None
            st.session_state["evr_all"] = None
            st.session_state["evp"] = None
            st.session_state["confirm_booking"] = None
            st.rerun()
    with c2:
        if st.button("Отмена", use_container_width=True):
            st.session_state["confirm_booking"] = None
            st.rerun()


# ═══ NAV ═══
page = st.sidebar.radio(
    "Навигация:",
    ["Инциденты", "Бронирование", "Отмена занятий", "Расписание", "Статистика", "Управление"],
)


# ═══ Страница 1: Инциденты ═══
if page == "Инциденты":
    st.title("Перенос занятий при закрытии аудиторий")
    ca, cb = st.columns(2)
    with ca:
        pt = st.radio("Тип:", ["Отдельные аудитории", "Весь корпус"])
        rms = get_rooms()
        ropts = {r["name"]: r for r in rms}
        if pt == "Отдельные аудитории":
            sn = st.multiselect("Аудитории:", list(ropts.keys()))
            sids_in = [ropts[n]["id"] for n in sn]
        else:
            sb = st.selectbox("Корпус:", get_buildings())
            sids_in = [r["id"] for r in rms if r["building"] == sb]

    with cb:
        st.write("**Период закрытия:**")
        today = date.today()
        d1, d2 = st.columns(2)
        with d1:
            sd = st.date_input("Начало:", value=today, min_value=date(2026, 1, 12))
        with d2:
            ed = st.date_input("Конец:", value=sd + timedelta(days=4), min_value=sd)

    st.divider()

    # Показываем уведомление о сохранении (из session_state)
    if st.session_state.get("saved_msg"):
        st.success(st.session_state["saved_msg"])
        if st.button("Новый перенос"):
            st.session_state["saved_msg"] = None
            st.session_state["ir"] = None
            st.session_state["ir_sd"] = None
            st.session_state["ir_ed"] = None
            st.rerun()
        st.divider()

    aff = get_affected(sids_in, sd, ed) if sids_in else []

    if st.button("Сгенерировать замены", type="primary", disabled=len(aff) == 0):
        with st.spinner("Оптимизация..."):
            st.session_state["ir"] = mass_reallocate([r["id"] for r in aff])
            st.session_state["ir_sd"] = sd
            st.session_state["ir_ed"] = ed

    res = st.session_state.get("ir")
    if res:
        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Перенесено", len(res.assignments))
        m2.metric("Не хватило", len(res.unassigned))
        m3.metric("Средний штраф", f"{res.avg_penalty:.1f}")
        m4.metric("Средний Match", f"{res.avg_match_percent:.1f}%")
        if res.assignments:
            # Считаем сколько дат для каждого (weekday, week_type)
            ir_sd = st.session_state.get("ir_sd", sd)
            ir_ed = st.session_state.get("ir_ed", ed)
            date_groups = {}
            dd = ir_sd
            while dd <= ir_ed:
                key = (d2wd(dd), d2wt(dd))
                date_groups[key] = date_groups.get(key, 0) + 1
                dd += timedelta(days=1)

            date_map = {}
            for r in aff:
                date_map[r["id"]] = r.get("booking_date", str(sd))

            # Группируем по (lesson_id, weekday, start, end) — чтобы не смешивать разные временные слоты
            lesson_display = {}  # (lid, weekday, start, end) -> dict
            for sid in sorted(res.assignments):
                s = res.assignments[sid]
                info = get_lesson_info(sid)
                lid = info["lesson_id"]
                wt_key = (info["weekday"], info["start"], info["end"], info["week_type"])
                n_dates = date_groups.get(wt_key, 1)
                bdate = date_map.get(sid, "")
                t_start = info["start"][11:16] if len(info["start"]) > 5 else info["start"]
                t_end = info["end"][11:16] if len(info["end"]) > 5 else info["end"]
                
                display_key = (lid, info["weekday"], info["start"], info["end"])
                if display_key not in lesson_display:
                    lesson_display[display_key] = {
                        "Время": slot_label(t_start, t_end),
                        "Тип": info["lesson_type"],
                        "Предмет": info["lesson_title"],
                        "Группы": [],
                        "Было": info["room_name"],
                        "Стало": f"{s.name} (корп.{s.building}, эт.{s.floor})",
                        "Штраф": s.penalty,
                        "%": f"{s.match_percent}%",
                        "n_dates": n_dates,
                        "first_date": bdate,
                    }
                    # Считаем студентов только для ЭТОГО временного слота
                    all_sids_for_this_slot = [sid2 for sid2 in res.assignments
                                               if get_lesson_info(sid2) and 
                                                  get_lesson_info(sid2)["lesson_id"] == lid and
                                                  get_lesson_info(sid2)["weekday"] == info["weekday"] and
                                                  get_lesson_info(sid2)["start"] == info["start"] and
                                                  get_lesson_info(sid2)["end"] == info["end"]]
                    total_st = sum(get_lesson_info(s2)["students_count"] for s2 in all_sids_for_this_slot)
                    n_groups = len(all_sids_for_this_slot)
                    need_proj = any(get_lesson_info(s2)["needs_projector"] for s2 in all_sids_for_this_slot)
                    need_comp = any(get_lesson_info(s2)["needs_computers"] for s2 in all_sids_for_this_slot)

                    req_parts = []
                    req_parts.append(f"{total_st} чел.")
                    if n_groups > 1:
                        req_parts[0] += f" ({n_groups} гр.)"
                    if need_proj:
                        req_parts.append("проектор")
                    if need_comp:
                        req_parts.append("компьютеры")
                    lesson_display[display_key]["Требования"] = " ".join(req_parts)

                lesson_display[display_key]["Группы"].append(info["group_name"])

            rd = []
            for display_key, ld in lesson_display.items():
                groups_str = ", ".join(sorted(set(ld["Группы"])))
                dates_str = ld["first_date"] if ld["n_dates"] <= 1 else f"{ld['first_date']} (+{ld['n_dates']-1} дн.)"
                row = {
                    "Дни": dates_str,
                    "Время": ld["Время"],
                    "Тип": ld["Тип"],
                    "Предмет": ld["Предмет"],
                    "Группы": groups_str,
                    "Требования": ld["Требования"],
                    "Было": ld["Было"],
                    "Стало": ld["Стало"],
                    "Штраф": ld["Штраф"],
                    "%": ld["%"],
                }
                rd.append(row)
            st.dataframe(pd.DataFrame(rd), width="stretch", hide_index=True)
            st.caption(f"«Требования»: кол-во студентов, проектор, компьютеры. «Дни» — первая дата и количество затронутых дней.")
            st.caption(f"Формула штрафа: разные корпуса +100, этаж ×5, лишние места ×1, ненужные компьютеры +10, ненужный проектор +5")
            if st.button("Сохранить замены", type="primary"):
                ir_sd = st.session_state.get("ir_sd", sd)
                ir_ed = st.session_state.get("ir_ed", ed)
                count = save_transfers(res.assignments, date_map, ir_sd, ir_ed)
                st.session_state["saved_msg"] = f"Успешно сохранено **{count}** переносов!"
                st.session_state["ir"] = None
                st.session_state["ir_sd"] = None
                st.session_state["ir_ed"] = None
                st.rerun()
        if res.unassigned:
            st.subheader("Не хватило")
            ua = [
                {
                    "Предмет": get_lesson_info(s)["lesson_title"],
                    "Группа": get_lesson_info(s)["group_name"],
                }
                for s in res.unassigned
            ]
            st.dataframe(pd.DataFrame(ua), width="stretch", hide_index=True)


# ═══ Страница 2: Бронирование ═══
elif page == "Бронирование":
    st.title("Бронирование мероприятия")

    if st.session_state.get("evd"):
        st.success(f"**{st.session_state['evd']}** забронирована на {st.session_state['evt']}!")
        if st.button("Забронировать ещё"):
            st.session_state["evd"] = None
            st.session_state["evt"] = None
            st.session_state["evr"] = None
            st.session_state["evp"] = None
            st.rerun()
        st.divider()

    c1, c2 = st.columns(2)
    with c1:
        en = st.text_input("Название:", value="Конференция", key="b_name")
        eo = st.text_input("Организатор:", value="Кафедра ИТ", key="b_org")
        ec = st.number_input("Участников:", min_value=1, max_value=500, value=30, key="b_att")
        ep = st.checkbox("Проектор", value=True, key="b_proj")
        ecomp = st.checkbox("Компьютеры", value=False, key="b_comp")
    with c2:
        st.write("**Дата и время:**")
        today = date.today()
        sel_date = st.date_input("Дата:", value=today, min_value=date(2026, 1, 12), key="b_date")
        wd = d2wd(sel_date)
        wt = d2wt(sel_date)
        st.caption(f"{wd} ({wt})")
        ts, te = st.columns(2)
        with ts:
            st_start = st.time_input(
                "Начало:", value=dt(2026, 1, 1, 9, 0).time(), key="b_tstart", step=300
            )
        with te:
            st_end = st.time_input(
                "Конец:", value=dt(2026, 1, 1, 10, 35).time(), key="b_tend", step=300
            )
    es = st_start.strftime("%H:%M")
    ee = st_end.strftime("%H:%M")

    st.divider()
    if st.button("Найти", type="primary"):
        if es >= ee:
            st.error("Время конца должно быть больше времени начала")
        else:
            with st.spinner("Поиск свободных аудиторий..."):
                res_all = find_room_for_event(ec, ep, ecomp, wd, to_iso(es, sel_date), to_iso(ee, sel_date), wt, 999, booking_date=str(sel_date))
            # Фильтруем аудитории с конфликтами
            res = []
            for r in res_all:
                if not check_booking_conflict(r["id"], sel_date, es, ee):
                    res.append(r)
            st.session_state["evr"] = res
            st.session_state["evr_all"] = res_all
            st.session_state["evp"] = {
                "n": en,
                "o": eo,
                "c": ec,
                "p": ep,
                "co": ecomp,
                "date": sel_date,
                "s": es,
                "e": ee,
                "wd": wd,
                "wt": wt,
            }

    res = st.session_state.get("evr")
    res_all = st.session_state.get("evr_all", [])
    par = st.session_state.get("evp", {})
    if res is not None:
        if len(res) == 0:
            reason = "Все найденные аудитории уже заняты в это время!" if len(res_all) > 0 else "Нет подходящих аудиторий"
            st.warning(f"{reason}")
            st.divider()
            st.subheader("Онлайн-формат")
            st.write("Нет доступных аудиторий? Проведите мероприятие онлайн!")
            col_onl1, col_onl2 = st.columns(2)
            with col_onl1:
                st.write(f"**Название:** {par.get('n', '?')}")
                st.write(f"**Организатор:** {par.get('o', '?')}")
                st.write(f"**Участников:** {par.get('c', '?')}")
            with col_onl2:
                st.write(f"**Дата:** {par.get('date', '?')}")
                st.write(f"**Время:** {par.get('s', '?')}–{par.get('e', '?')}")
            if st.button("Забронировать онлайн", type="secondary"):
                st.success(f"Мероприятие \"{par.get('n', '?')}\" будет проведено онлайн!")
        elif len(res) > 0:
            st.subheader(f"Результаты: {par.get('date','?')} {par.get('s','?')}–{par.get('e','?')}")
            for i, r in enumerate(res, 1):
                with st.container(border=True):
                    a, b, c = st.columns([2, 2, 1])
                    with a:
                        st.write(f"**#{i} {r['name']}**")
                        st.caption(f"Корп.{r['building']}, эт.{r['floor']}")
                    with b:
                        w = r["capacity"] - par.get("c", 0)
                        st.write(f"Вместимость: {r['capacity']} (избыток {w})")
                        eq = []
                        if r["has_projector"]:
                            eq.append("Проектор")
                        if r["has_computers"]:
                            eq.append("Компьютеры")
                        st.write(", ".join(eq) if eq else "—")
                    with c:
                        if st.button("Забронировать", key=f"bk{i}"):
                            st.session_state["confirm_booking"] = {
                                "room": dict(r),
                                "par": par,
                            }

    confirm = st.session_state.get("confirm_booking")
    if confirm:
        _show_booking_confirm_dialog(confirm)


# ═══ Страница 3: Отмена занятий ═══
elif page == "Отмена занятий":
    st.title("Отмена и восстановление занятий")
    tab_cancel, tab_restore, tab_log = st.tabs(["Отмена", "Восстановление", "Журнал"])

    with tab_cancel:
        ct = st.radio("Тип отмены:", ["По преподавателю", "По дисциплине", "Одиночная"], horizontal=True)
        ca, cb = st.columns(2)
        with ca:
            if ct == "По преподавателю":
                teachers = get_all_teachers()
                sel_teacher = st.selectbox("Преподаватель:", teachers, key="cn_teacher")
            elif ct == "По дисциплине":
                disciplines = get_all_disciplines()
                sel_disc = st.selectbox("Дисциплина:", disciplines, key="cn_disc")
            else:
                c = gc()
                all_sched = c.execute("""
                    SELECT s.id, l.title || ' (' || l.lesson_type || ') — ' ||
                           g.name || ' — ' || s.weekday || ' ' ||
                           substr(s.start,12,5) AS label
                    FROM schedule s
                    JOIN lessons l ON s.lesson_id = l.id
                    JOIN groups g ON s.group_id = g.id
                    ORDER BY l.title, s.weekday
                """).fetchall()
                c.close()
                sched_opts = {r["label"]: r["id"] for r in all_sched}
                sel_sched_label = st.selectbox("Занятие:", list(sched_opts.keys()), key="cn_single")
                sel_sched_id = sched_opts.get(sel_sched_label)
        with cb:
            today = date.today()
            d1, d2 = st.columns(2)
            with d1:
                cn_sd = st.date_input("Начало:", value=today, min_value=date(2026, 1, 12), key="cn_sd")
            with d2:
                cn_ed = st.date_input("Конец:", value=cn_sd + timedelta(days=13), min_value=cn_sd, key="cn_ed")
            if ct == "Одиночная":
                cn_single_date = st.date_input("Дата отмены:", value=today, min_value=date(2026, 1, 12), key="cn_single_date")
            cn_reason = st.text_input("Причина:", value="Болезнь преподавателя", key="cn_reason")

        st.divider()

        if st.button("Предпросмотр", type="primary", key="cn_preview_btn"):
            if ct == "По преподавателю":
                previews = preview_cancel_by_teacher(sel_teacher, cn_sd, cn_ed)
            elif ct == "По дисциплине":
                previews = preview_cancel_by_discipline(sel_disc, cn_sd, cn_ed)
            else:
                if sel_sched_id:
                    previews = preview_cancel_single(sel_sched_id, cn_single_date)
                else:
                    previews = []
            st.session_state["cn_previews"] = previews

        previews = st.session_state.get("cn_previews", [])
        if previews:
            st.info(f"Будет отменено: **{len(previews)}** занятий")
            cn_df = pd.DataFrame([{
                "Дата": p.cancel_date,
                "Предмет": p.lesson_title,
                "Тип": p.lesson_type,
                "Преподаватель": p.teacher,
                "Группа": p.group_name,
                "Аудитория": p.room_name,
                "День": p.weekday,
                "Время": f"{p.start}–{p.end}",
            } for p in previews])
            st.dataframe(cn_df, width="stretch", hide_index=True)

            if st.button("Подтвердить отмену", type="primary", key="cn_apply_btn"):
                count = apply_cancels(previews, cn_reason)
                st.session_state["cn_previews"] = []
                st.session_state["cn_msg"] = f"Отменено **{count}** занятий"
                st.rerun()

        if st.session_state.get("cn_msg"):
            st.success(st.session_state["cn_msg"])
            if st.button("Новая отмена", key="cn_new"):
                st.session_state["cn_msg"] = None
                st.rerun()

    with tab_restore:
        c = gc()
        active = c.execute("""
            SELECT c.id, c.cancel_date, c.reason,
                   l.title AS lesson_title, l.lesson_type, l.teacher,
                   g.name AS group_name,
                   s.weekday, substr(s.start,12,5) as st, substr(s.end,12,5) as et
            FROM cancellations c
            JOIN schedule s ON c.schedule_id = s.id
            JOIN lessons l ON s.lesson_id = l.id
            JOIN groups g ON s.group_id = g.id
            WHERE c.is_restored = 0
            ORDER BY c.cancel_date DESC
        """).fetchall()
        c.close()

        if not active:
            st.info("Нет отменённых занятий для восстановления")
        else:
            r_opts = {}
            for r in active:
                label = f"{r['cancel_date']} | {r['lesson_title']} ({r['lesson_type']}) — {r['group_name']} — {r['weekday']} {r['st']}–{r['et']}"
                r_opts[label] = r["id"]

            restore_mode = st.radio("Режим:", ["Одиночное", "Массовое"], horizontal=True, key="rs_mode")

            if restore_mode == "Массовое":
                sel_labels = st.multiselect("Отменённые занятия:", list(r_opts.keys()), key="rs_multi")
                sel_cids = [r_opts[l] for l in sel_labels if l in r_opts]

                if sel_cids:
                    st.info(f"Выбрано **{len(sel_cids)}** занятий для восстановления")
                    if st.button("Предпросмотр восстановления", type="primary", key="rs_mass_preview_btn"):
                        with st.spinner("Поиск свободных слотов..."):
                            pv = mass_restore_preview(sel_cids)
                        st.session_state["rs_mass_pv"] = pv
                        st.session_state["rs_mass_cids"] = sel_cids

                    pv = st.session_state.get("rs_mass_pv")
                    if pv:
                        has_slots = [p for p in pv if p["has_slot"]]
                        no_slots = [p for p in pv if not p["has_slot"]]
                        m1, m2 = st.columns(2)
                        m1.metric("Можно восстановить", len(has_slots))
                        m2.metric("Нет свободных слотов", len(no_slots))

                        if has_slots:
                            st.subheader("План восстановления")
                            pv_df = pd.DataFrame([{
                                "Предмет": p["lesson_title"],
                                "Тип": p["lesson_type"],
                                "Группы": p["group_names"],
                                "Было": f'{p["orig_weekday"]} {p["orig_start"]}–{p["orig_end"]}',
                                "Было ауд.": p["orig_room"],
                                "Станет": f'{p["new_weekday"]} {p["new_start"]}–{p["new_end"]}',
                                "Станет ауд.": p["new_room"],
                                "Дата восстановления": p["new_date"],
                                "Штраф": p["penalty"],
                            } for p in has_slots])
                            st.dataframe(pv_df, width="stretch", hide_index=True)

                        if no_slots:
                            st.warning(f"**{len(no_slots)}** занятий — нет свободных слотов:")
                            for p in no_slots:
                                st.write(f"  • {p['lesson_title']} ({p['group_names']}) — {p['orig_weekday']} {p['orig_start']}")

                        if has_slots and st.button("Подтвердить восстановление", type="primary", key="rs_mass_confirm_btn"):
                            cids_to_restore = [p["cancel_id"] for p in has_slots]
                            with st.spinner("Восстановление..."):
                                result = mass_restore(cids_to_restore)
                            st.session_state["rs_mass_result"] = result
                            st.session_state["rs_mass_pv"] = None
                            st.rerun()

                if st.session_state.get("rs_mass_result"):
                    mr = st.session_state["rs_mass_result"]
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Восстановлено", mr["restored"])
                    m2.metric("Нет слотов", mr["no_slots"])
                    m3.metric("Ошибки", mr["failed"])
                    if mr["details"]:
                        st.subheader("Результаты восстановления")
                        det_df = pd.DataFrame([{
                            "Предмет": d.get("lesson_title", ""),
                            "Тип": d.get("lesson_type", ""),
                            "Группа": d.get("group_name", ""),
                            "Статус": "Восстановлено" if d["status"] == "restored" else "Нет слотов",
                            "Новый слот": f'{d.get("new_weekday", "")} {d.get("new_start", "")}–{d.get("new_end", "")}' if d["status"] == "restored" else "—",
                            "Новая аудитория": d.get("new_room", "—"),
                            "Штраф": d.get("penalty", "—"),
                        } for d in mr["details"]])
                        st.dataframe(det_df, width="stretch", hide_index=True)
                    if st.button("Новое восстановление", key="rs_mass_new"):
                        st.session_state["rs_mass_result"] = None
                        st.rerun()

            else:
                sel_label = st.selectbox("Отменённое занятие:", list(r_opts.keys()), key="rs_sel")
                sel_cid = r_opts.get(sel_label)

                if sel_cid and st.button("Найти слоты для восстановления", type="primary", key="rs_find_btn"):
                    with st.spinner("Поиск свободных слотов..."):
                        slots = find_restore_slots(sel_cid)
                    st.session_state["rs_slots"] = slots
                    st.session_state["rs_cid"] = sel_cid

                slots = st.session_state.get("rs_slots", [])
                rs_cid = st.session_state.get("rs_cid")

                if slots:
                    st.info(f"Найдено **{len(slots)}** вариантов восстановления")
                    for i, sl in enumerate(slots, 1):
                        with st.container(border=True):
                            sa, sb, sc = st.columns([3, 2, 1])
                            with sa:
                                date_str = sl.restore_date if sl.restore_date else "—"
                                st.write(f"**{date_str}** | {sl.weekday}, {sl.start}–{sl.end}")
                                st.caption(f"Аудитория: {sl.room_name} (корп.{sl.room_building}, эт.{sl.room_floor}, {sl.room_capacity} мест)")
                            with sb:
                                st.metric("Штраф", sl.penalty)
                                st.caption(f"Пригодность: {sl.match_percent}%")
                            with sc:
                                if st.button("Восстановить", key=f"rs_do_{i}"):
                                    new_sid = restore_lesson(rs_cid, sl)
                                    st.session_state["rs_slots"] = None
                                    st.session_state["rs_cid"] = None
                                    if new_sid:
                                        st.session_state["cn_msg"] = f"Занятие восстановлено (schedule_id={new_sid})"
                                    else:
                                        st.session_state["cn_msg"] = "Не удалось восстановить"
                                    st.rerun()
                elif slots is not None and len(slots) == 0:
                    st.warning("Нет подходящих свободных слотов для восстановления")

    with tab_log:
        all_cn = get_cancellations()
        if not all_cn:
            st.info("Нет записей об отменах")
        else:
            log_df = pd.DataFrame([{
                "Дата изменения": str(r["created_at"])[:19] if r["created_at"] else "—",
                "Дата отмены": r["cancel_date"],
                "Предмет": r["lesson_title"],
                "Тип": r["lesson_type"],
                "Преподаватель": r["teacher"] or "—",
                "Группа": r["group_name"],
                "Причина": r["reason"] or "—",
                "Статус": "Восстановлено" if r["is_restored"] else "Отменено",
                "Было": f'{r["weekday"]} {t_from_iso(r["start"])}–{t_from_iso(r["end"])} ({r["room_name"]})',
                "Стало": f'{r["restored_weekday"] or "—"} {t_from_iso(r["restored_start"])}–{t_from_iso(r["restored_end"])} ({r["restored_room_name"]})' if r["is_restored"] else "—",
            } for r in all_cn])
            st.dataframe(log_df, width="stretch", hide_index=True)


# ═══ Страница 4: Расписание ═══
elif page == "Расписание":
    st.title("Расписание")
    f0, f1 = st.columns([1, 2])
    with f0:
        sel_date = st.date_input(
            "Дата:", value=date.today(), min_value=date(2026, 1, 12), key="sched_date"
        )
    with f1:
        fb = st.selectbox("Корпус:", ["Все"] + get_buildings())

    sg, sel_wd, sel_wt = get_sched_for_date(sel_date)
    rms = get_rooms()
    if fb != "Все":
        rms = [r for r in rms if r["building"] == fb]

    transfers_date = get_transfers_for_date(sel_date)

    active_cancels = get_active_cancellations_for_date(sel_date)
    cancel_sids = set(r["schedule_id"] for r in active_cancels)
    cancel_map = {}
    for r in active_cancels:
        cancel_map[(r["room_id"], r["start"][11:16] if len(r["start"]) > 5 else r["start"])] = r

    restored_rows = get_restored_for_date(sel_date)
    restored_map = {}
    for r in restored_rows:
        restored_map[(r["room_id"], r["start"][11:16] if len(r["start"]) > 5 else r["start"])] = r

    # Объединяем группы для лекций (несколько schedule_id → один lesson_id)
    merged_transfers = {}
    for t in transfers_date:
        k = (t["lesson_title"], t["st"], t["et"])
        if k not in merged_transfers:
            merged_transfers[k] = {
                "lesson_title": t["lesson_title"],
                "group_names": [t["group_name"]],
                "old_room": t["old_room"],
                "new_room": t["new_room"],
                "new_room_id": t["new_room_id"],
                "st": t["st"],
                "et": t["et"],
                "schedule_ids": {t["schedule_id"]},
                "lesson_type": t["lesson_type"],
            }
        else:
            merged_transfers[k]["group_names"].append(t["group_name"])
            merged_transfers[k]["schedule_ids"].add(t["schedule_id"])

    atr = {}
    tsids = set()
    for k, mt in merged_transfers.items():
        atr[(mt["new_room_id"], mt["st"])] = mt
        tsids.update(mt["schedule_ids"])

    abk = {}
    for rm in rms:
        bks = get_bookings_for_date(rm["id"], sel_date)
        if bks:
            abk[rm["id"]] = bks

    sm = {}
    for r in sg:
        sm[(r["room_id"], r["start"])] = r

    st.subheader(f"{sel_date.strftime('%d.%m.%Y')} — {sel_wd} ({sel_wt})")

    h = '<table style="border-collapse:collapse;width:100%;font-size:12px;">'
    h += '<tr><th style="border:1px solid #ccc;padding:4px;background:#f0f0f0;position:sticky;left:0;z-index:2;">Аудитория</th>'
    for sl in SLOTS:
        h += f'<th style="border:1px solid #ccc;padding:4px;background:#f0f0f0;text-align:center;font-size:11px;">{sl["name"]}<br>{sl["start"]}–{sl["end"]}</th>'
    h += "</tr>"

    for rm in rms:
        cap = rm["capacity"]
        eq_parts = []
        if rm["has_projector"]:
            eq_parts.append("📽")
        if rm["has_computers"]:
            eq_parts.append("💻")
        eq_str = " ".join(eq_parts) if eq_parts else "—"
        h += f'<tr><td style="border:1px solid #ccc;padding:4px;font-weight:bold;background:#fafafa;position:sticky;left:0;font-size:12px;">{rm["name"]}<br><small>{cap} мест {eq_str}</small></td>'
        for sl in SLOTS:
            s, e = sl["start"], sl["end"]
            sk = (rm["id"], s)
            sc = sm.get(sk)
            td = atr.get((rm["id"], s))

            cell = ""
            bg = "#fff"
            bl = "3px solid transparent"

            restored_entry = restored_map.get((rm["id"], s))
            if restored_entry:
                re = restored_entry
                cell = (
                    f'<div style="font-weight:bold;color:#5b21b6;">🔄 {re["lesson_title"]}</div>'
                    f'<div style="font-size:9px;">{re["lesson_type"]}<br>{re["group_name"]}</div>'
                    f'<div style="font-size:8px;color:#7c3aed;">Восстановлено</div>'
                )
                bg, bl = "#ede9fe", "3px solid #7c3aed"
            elif td:
                groups_str = ", ".join(sorted(set(td.get("group_names", [td.get("group_name", "")]))))
                lesson_type = td.get("lesson_type", "")
                type_label = f"<small>{lesson_type}</small><br>" if lesson_type else ""
                cell = (
                    f'<div style="font-weight:bold;color:#065f46;">✅ {td["lesson_title"]}</div>'
                    f'{type_label}'
                    f'<div style="font-size:10px;">{groups_str}</div>'
                    f'<div style="font-size:9px;color:#6b7280;">← {td["old_room"]}</div>'
                )
                bg, bl = "#d1fae5", "3px solid #059669"
            elif sc:
                if any(x in cancel_sids for x in sc["sids"]):
                    cn_info = cancel_map.get((rm["id"], s))
                    reason_str = f'<div style="font-size:8px;color:#6b7280;">{cn_info["reason"]}</div>' if cn_info and cn_info["reason"] else ""
                    cell = (
                        f'<div style="font-weight:bold;color:#6b7280;text-decoration:line-through;">🚫 {sc["lesson_title"]}</div>'
                        f'<div style="font-size:9px;color:#9ca3af;">{sc["lesson_type"]} | {sc["gd"]}</div>'
                        f'{reason_str}'
                        f'<div style="font-size:8px;color:#9ca3af;">ОТМЕНЕНО</div>'
                    )
                    bg, bl = "#f3f4f6", "3px solid #9ca3af"
                elif any(x in tsids for x in sc["sids"]):
                    mt = None
                    for x in sc["sids"]:
                        if x in tsids:
                            for t2 in transfers_date:
                                if t2["schedule_id"] == x:
                                    mt = t2["new_room"]
                                    break
                            if mt:
                                break
                        if mt:
                            break
                    cell = (
                        f'<div style="font-weight:bold;color:#991b1b;text-decoration:line-through;">❌ {sc["lesson_title"]}</div>'
                        f'<div style="font-size:9px;">{sc["lesson_type"]} | {sc["gd"]}</div>'
                        f'<div style="font-size:9px;color:#dc2626;">→ {mt}</div>'
                    )
                    bg, bl = "#fee2e2", "3px solid #dc2626"
                else:
                    lec = sc["lesson_type"] == "Лекционные"
                    cell = (
                        f'<div style="font-weight:bold;color:#1e40af;font-size:11px;">{sc["lesson_title"]}</div>'
                        f'<div style="font-size:9px;color:#374151;">{sc["lesson_type"]}<br>{sc["gd"]}</div>'
                    )
                    bg, bl = ("#bfdbfe", "3px solid #3b82f6") if lec else ("#dbeafe", "3px solid #3b82f6")

            for bkk in abk.get(rm["id"], []):
                bk_s = t2m(bkk["st"])
                bk_e = t2m(bkk["et"])
                sl_s = t2m(s)
                sl_e = t2m(e)
                if bk_s < sl_e and bk_e > sl_s:
                    cell += (
                        f'<div style="font-size:10px;font-weight:bold;color:#92400e;margin-top:2px;">📌 {bkk["event_name"]}</div>'
                        f'<div style="font-size:9px;">{bkk["organizer"]} | {bkk["attendees_count"]}ч.</div>'
                        f'<div style="font-size:8px;color:#6b7280;">{bkk["st"]}–{bkk["et"]}</div>'
                    )
                    if "fee2e2" not in cell and "d1fae5" not in cell:
                        bg, bl = "#fef3c7", "3px solid #f59e0b"

            if cell:
                h += f'<td style="border:1px solid #ccc;padding:4px;background:{bg};border-left:{bl};vertical-align:top;">{cell}</td>'
            else:
                h += '<td style="border:1px solid #ccc;padding:4px;background:#f9f9f9;color:#ddd;text-align:center;">—</td>'
        h += "</tr>"
    h += "</table>"
    st.markdown("🟦 Занятие | 🟩 Перенесено сюда | 🟥 Перенесено отсюда | 🟨 Мероприятие | 🟪 Восстановлено | ⬜ Отменено")
    st.markdown(h, unsafe_allow_html=True)


# ═══ Страница 4: Статистика ═══
elif page == "Статистика":
    st.title("Статистика аудиторного фонда")

    pc = pc_utilization()
    cd = capacity_demand()
    td = transfer_destinations()
    fs = fund_summary_with_transfers()

    # ── 1. Сводка по фонду ──
    st.subheader("Сводка по аудиторному фонду")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Аудиторий", fs["rooms"])
    m2.metric("Корпусов", fs["buildings"])
    m3.metric("Уникальных занятий", fs["unique_lesson_slots"])
    m4.metric("Учебных групп", fs["groups"])

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Записей в расписании", fs["schedule_entries"])
    m6.metric("Общая вместимость", f'{fs["total_capacity"]} мест')
    m7.metric("Бронирований", fs["bookings"])
    m8.metric("Переносов", fs["transfers"])

    # ── 2. Компьютерные классы ──
    st.subheader("Использование компьютерных классов")
    st.caption("Компьютерные классы — дефицитный ресурс. Если они заняты обычными занятиями, лабораторным не хватает ПК.")

    comp_df = pd.DataFrame([{
        "Метрика": "Компьютерных аудиторий",
        "Значение": pc["rooms_total"],
    }, {
        "Метрика": "Занятий, требующих ПК",
        "Значение": pc["lessons_needing_pc"],
    }, {
        "Метрика": "Используются по назначению",
        "Значение": pc["rooms_for_comp"],
    }, {
        "Метрика": "Заняты обычными занятиями (трата ресурса)",
        "Значение": pc["rooms_for_noncomp"],
    }, {
        "Метрика": "Слотов с ПК-занятиями",
        "Значение": pc["slots_for_comp"],
    }, {
        "Метрика": "Слотов с обычными занятиями впустую",
        "Значение": pc["slots_for_noncomp"],
    }])
    st.dataframe(comp_df, width="stretch", hide_index=True)

    if pc["wasted_rooms"]:
        st.write("**Компьютерные классы, где больше всего «пустых» слотов:**")
        wr_df = pd.DataFrame([{
            "Аудитория": r["name"],
            "Корпус": r["building"],
            "Вместимость": r["capacity"],
            "Всего занятий": r["total_slots"],
            "Из них без потребности в ПК": r["wasted_slots"],
        } for r in pc["wasted_rooms"]])
        st.dataframe(wr_df, width="stretch", hide_index=True)

    if pc["rooms_for_noncomp"] > 0:
        pct_waste = round(pc["slots_for_noncomp"] / (pc["slots_for_comp"] + pc["slots_for_noncomp"]) * 100, 1) if (pc["slots_for_comp"] + pc["slots_for_noncomp"]) > 0 else 0
        st.warning(
            f"**Вывод:** {pc['rooms_for_noncomp']} из {pc['rooms_total']} компьютерных классов "
            f"заняты обычными занятиями. {pct_waste}% слотов дефицитного ресурса "
            f"тратятся впустую. Рекомендуется пересмотреть расписание и освободить "
            f"компьютерные классы для занятий, реально требующих ПК."
        )
    else:
        st.info("**Вывод:** Все компьютерные классы используются по назначению — дефицита нет.")

    # ── 3. Вместимость ──
    st.subheader("Загрузка по вместимости")
    st.caption("Сравнение слотов: сколько занято vs сколько доступно. Переполнение — занятия, которым нужна эта категория, но стоят в большей из-за отсутствия подходящих.")

    cd_df = pd.DataFrame([{
        "Вместимость": r["range"],
        "Аудиторий": r["rooms"],
        "Слотов доступно": r["total_slots"],
        "Слотов занято": r["occupied_slots"],
        "Загрузка": f'{r["load_pct"]}%',
        "Переполнение": r["overflow"],
    } for r in cd])
    st.dataframe(cd_df, width="stretch", hide_index=True)

    cd_chart = pd.DataFrame([{
        "Вместимость": r["range"],
        "Занято": r["occupied_slots"],
        "Свободно": r["free_slots"],
    } for r in cd if r["total_slots"] > 0])
    if not cd_chart.empty:
        st.bar_chart(cd_chart, x="Вместимость", y=["Занято", "Свободно"])

    overflow_ranges = [r for r in cd if r["overflow"] > 0]
    high_load = [r for r in cd if r["load_pct"] > 70 and r["overflow"] == 0]
    low_load = [r for r in cd if r["total_slots"] > 0 and r["load_pct"] < 15]

    if overflow_ranges:
        labels = ", ".join(f"{r['range']} ({r['overflow']} занятий)" for r in overflow_ranges)
        st.warning(
            f"**Переполнение:** Нет аудиторий вместимостью {labels}. "
            f"Эти занятия ставятся в более крупные аудитории — перерасход фонда. "
            f"Рекомендуется добавить малые аудитории (перегородки, переговорки)."
        )
    if high_load:
        labels = ", ".join(f"{r['range']} ({r['load_pct']}%)" for r in high_load)
        st.warning(
            f"**Высокая загрузка:** Категория {labels}. "
            f"При инцидентах может не хватить свободных слотов для переноса."
        )
    if low_load:
        labels = ", ".join(f"{r['range']} ({r['load_pct']}%)" for r in low_load)
        st.info(
            f"**Резерв:** Категория {labels} — много свободных слотов, "
            f"можно использовать для переноса занятий при инцидентах."
        )
    if not overflow_ranges and not high_load:
        st.info("**Вывод:** Аудиторный фонд сбалансирован по вместимости — критического дефицита нет.")

    # ── 4. Переносы ──
    st.subheader("Аудитории — получатели переносов")
    if td["total_transfers"] == 0:
        st.info("Переносов ещё не было. Данные появятся после использования страницы «Инциденты».")
    else:
        st.caption("Аудитории, которые чаще всего принимают перенесённые занятия — «рабочие лошадки»")
        td_df = pd.DataFrame([{
            "Аудитория": r["name"],
            "Корпус": r["building"],
            "Вместимость": r["capacity"],
            "Принято переносов": r["transfer_count"],
            "Дат затронуто": r["dates_affected"],
        } for r in td["top_rooms"]])
        st.dataframe(td_df, width="stretch", hide_index=True)

        if td["top_rooms"]:
            top = td["top_rooms"][0]
            st.info(
                f"**Вывод:** Аудитория **{top['name']}** (корп. {top['building']}) — "
                f"основной получатель переносов ({top['transfer_count']} из {td['total_transfers']}). "
                f"Её закрытие критично для системы корректировки расписания."
            )

        m1, m2, m3 = st.columns(3)
        m1.metric("Всего корректировок", fs["transfers"])
        m2.metric("Дат затронуто", fs["transfer_dates"])
        m3.metric("Аудиторий задействовано", fs["transfer_rooms"])


# ═══ Страница 5: Управление ═══
elif page == "Управление":
    st.title("Управление переносами и бронированиями")
    t1, t2, t3 = st.tabs(["Переносы", "Бронирования", "Отмены"])

    with t1:
        # Загрузка всех переносов
        c = gc()
        trs_raw = c.execute("""
            SELECT t.*,r1.name as old_room,r2.name as new_room,
                   l.title as lesson_title,l.lesson_type,g.name as group_name
            FROM transfers t JOIN rooms r1 ON t.old_room_id=r1.id
            JOIN rooms r2 ON t.new_room_id=r2.id
            JOIN lessons l ON t.lesson_id=l.id JOIN groups g ON t.group_id=g.id
            ORDER BY t.booking_date DESC, t.start""").fetchall()
        c.close()

        if not trs_raw:
            st.info("Нет переносов")
        else:
            # Группируем по (booking_date, lesson_title, start, end, new_room)
            trs_grouped = {}
            for t in trs_raw:
                td = dict(t)
                bdate = td.get("booking_date") or "?"
                t_s = t_from_iso(t["start"])
                t_e = t_from_iso(t["end"])
                k = (bdate, t["lesson_title"], t_s, t_e, t["new_room"], t["old_room"])
                if k not in trs_grouped:
                    trs_grouped[k] = {
                        "booking_date": bdate,
                        "lesson_title": t["lesson_title"],
                        "lesson_type": td.get("lesson_type") or "",
                        "start": t_s,
                        "end": t_e,
                        "new_room": t["new_room"],
                        "old_room": t["old_room"],
                        "groups": [t["group_name"]],
                        "ids": [t["id"]],
                        "created_at": td.get("created_at", ""),
                    }
                else:
                    trs_grouped[k]["groups"].append(t["group_name"])
                    trs_grouped[k]["ids"].append(t["id"])

            trs_list = list(trs_grouped.values())

            # Фильтры — пустой = все
            st.subheader("Фильтры")
            f0, f1, f2, f3 = st.columns(4)
            with f0:
                dates_list = sorted(set(x["booking_date"] for x in trs_list))
                sel_dates = st.multiselect("Дата:", dates_list, key="f_dates")
            with f1:
                subjects = sorted(set(x["lesson_title"] for x in trs_list))
                sel_subjects = st.multiselect("Предмет:", subjects, key="f_subjects")
            with f2:
                old_rooms = sorted(set(x["old_room"] for x in trs_list))
                sel_rooms = st.multiselect("Из аудитории:", old_rooms, key="f_rooms")
            with f3:
                all_grps = set()
                for x in trs_list:
                    all_grps.update(x["groups"])
                sel_groups = st.multiselect("Группа:", sorted(all_grps), key="f_groups")

            # Применяем: пустой фильтр = все
            trs = [x for x in trs_list
                   if (not sel_dates or x["booking_date"] in sel_dates)
                   and (not sel_subjects or x["lesson_title"] in sel_subjects)
                   and (not sel_rooms or x["old_room"] in sel_rooms)
                   and (not sel_groups or any(g in sel_groups for g in x["groups"]))]

            # Подсчёт записей (raw — сколько записей в БД)
            total_db_records = sum(len(x["ids"]) for x in trs_list)
            shown_records = sum(len(x["ids"]) for x in trs)

            st.divider()
            col_show, col_del = st.columns([3, 1])
            with col_show:
                st.info(f"Показано: **{len(trs)}** переносов ({shown_records} записей в БД)")
            with col_del:
                if st.button("Удалить ВСЕ переносы", type="secondary", key="del_all_transfers"):
                    c = gc()
                    c.execute("DELETE FROM transfers")
                    c.commit()
                    c.close()
                    st.success("Удалены все переносы!")
                    st.rerun()

                if trs and len(trs) < len(trs_list):
                    if st.button("Удалить отфильтрованные", type="secondary", key="del_filtered_transfers"):
                        ids_to_del = []
                        for x in trs:
                            ids_to_del.extend(x["ids"])
                        c = gc()
                        c.execute(f"DELETE FROM transfers WHERE id IN ({','.join('?' for _ in ids_to_del)})", ids_to_del)
                        c.commit()
                        c.close()
                        st.success(f"Удалено {len(ids_to_del)} записей!")
                        st.rerun()

            for item in trs:
                with st.container(border=True):
                    aa, bb, cc, dd = st.columns([2, 2, 3, 1])
                    with aa:
                        st.write(f"**{item['lesson_title']}**")
                        groups_str = ", ".join(sorted(set(item["groups"])))
                        type_str = f" ({item['lesson_type']})" if item.get("lesson_type") else ""
                        st.caption(f"{groups_str}{type_str}")
                    with bb:
                        bdate = item["booking_date"]
                        slabel = slot_label(item["start"], item["end"])
                        st.write(f"{bdate}")
                        st.caption(slabel)
                    with cc:
                        st.write(f"{item['old_room']} → **{item['new_room']}**")
                        st.caption(f"Записей в БД: {len(item['ids'])}")
                    with dd:
                        if st.button("X", key=f"dt{item['ids'][0]}"):
                            for tid in item["ids"]:
                                del_transfer(tid)
                            st.success(f"Удалено {len(item['ids'])} записей")
                            st.rerun()
    with t2:
        c = gc()
        bks_all = c.execute("""
            SELECT eb.*,r.name as room_name,r.building,r.floor
            FROM event_bookings eb JOIN rooms r ON eb.room_id=r.id
            ORDER BY eb.booking_date DESC""").fetchall()
        c.close()

        if not bks_all:
            st.info("Нет бронирований")
        else:
            st.subheader("Фильтры")
            f0, f1, f2 = st.columns(3)
            with f0:
                dates_list = sorted(set(dict(b).get("booking_date") for b in bks_all if dict(b).get("booking_date")))
                sel_dates = st.multiselect("Дата:", dates_list, key="bk_f_dates")
            with f1:
                rooms_list = sorted(set(b["room_name"] for b in bks_all))
                sel_rooms = st.multiselect("Аудитория:", rooms_list, key="bk_f_rooms")
            with f2:
                events_list = sorted(set(b["event_name"] for b in bks_all))
                sel_events = st.multiselect("Мероприятие:", events_list, key="bk_f_events")

            bks = [b for b in bks_all
                   if (not sel_dates or dict(b).get("booking_date") in sel_dates)
                   and (not sel_rooms or b["room_name"] in sel_rooms)
                   and (not sel_events or b["event_name"] in sel_events)]

            st.divider()
            col_show, col_del = st.columns([3, 1])
            with col_show:
                st.info(f"Показано: **{len(bks)}** из {len(bks_all)} бронирований")
            with col_del:
                if st.button("Удалить ВСЕ бронирования", type="secondary", key="del_all_bookings"):
                    c = gc()
                    c.execute("DELETE FROM event_bookings")
                    c.commit()
                    c.close()
                    st.success(f"Удалено все {len(bks_all)} бронирований!")
                    st.rerun()
                if bks and len(bks) < len(bks_all):
                    if st.button("Удалить отфильтрованные", type="secondary", key="del_filtered_bookings"):
                        ids = [b["id"] for b in bks]
                        c = gc()
                        c.execute(f"DELETE FROM event_bookings WHERE id IN ({','.join('?' for _ in ids)})", ids)
                        c.commit()
                        c.close()
                        st.success(f"Удалено {len(ids)} бронирований!")
                        st.rerun()

            for b in bks:
                with st.container(border=True):
                    aa, bb, cc, dd = st.columns([2, 2, 3, 1])
                    with aa:
                        st.write(f"**{b['event_name']}**")
                        st.caption(f"{b['organizer']} | {b['attendees_count']} чел.")
                    with bb:
                        bdate = dict(b).get("booking_date") or "?"
                        b_s = t_from_iso(b["start"])
                        b_e = t_from_iso(b["end"])
                        slabel = slot_label(b_s, b_e)
                        st.write(f"{bdate}")
                        st.caption(slabel)
                    with cc:
                        st.write(f"{b['room_name']} (корп.{b['building']}, эт.{b['floor']})")
                    with dd:
                        if st.button("X", key=f"db{b['id']}"):
                            del_booking(b["id"])
                            st.success("Удалено")
                            st.rerun()

    with t3:
        all_cancels = get_cancellations()
        if not all_cancels:
            st.info("Нет отмен")
        else:
            st.subheader("Фильтры")
            f0, f1, f2 = st.columns(3)
            with f0:
                cn_dates = sorted(set(r["cancel_date"] for r in all_cancels))
                sel_cn_dates = st.multiselect("Дата:", cn_dates, key="mg_cn_dates")
            with f1:
                cn_reasons = sorted(set(r["reason"] or "" for r in all_cancels))
                sel_cn_reasons = st.multiselect("Причина:", cn_reasons, key="mg_cn_reasons")
            with f2:
                cn_statuses = ["Активные", "Восстановленные", "Все"]
                sel_cn_status = st.selectbox("Статус:", cn_statuses, key="mg_cn_status")

            filtered = [r for r in all_cancels
                        if (not sel_cn_dates or r["cancel_date"] in sel_cn_dates)
                        and (not sel_cn_reasons or (r["reason"] or "") in sel_cn_reasons)
                        and (sel_cn_status == "Все"
                             or (sel_cn_status == "Активные" and not r["is_restored"])
                             or (sel_cn_status == "Восстановленные" and r["is_restored"]))]

            st.divider()
            col_show, col_del = st.columns([3, 1])
            with col_show:
                st.info(f"Показано: **{len(filtered)}** из {len(all_cancels)} отмен")
            with col_del:
                if st.button("Удалить ВСЕ отмены", type="secondary", key="del_all_cancels"):
                    c = gc()
                    restored_sids = c.execute("SELECT restored_schedule_id FROM cancellations WHERE is_restored = 1 AND restored_schedule_id IS NOT NULL").fetchall()
                    for r in restored_sids:
                        c.execute("DELETE FROM schedule WHERE id = ?", (r[0],))
                    c.execute("DELETE FROM cancellations")
                    c.commit()
                    c.close()
                    st.success("Удалены все отмены!")
                    st.rerun()

            for r in filtered:
                with st.container(border=True):
                    aa, bb, cc, dd = st.columns([2, 2, 3, 1])
                    with aa:
                        st.write(f"**{r['lesson_title']}**")
                        st.caption(f"{r['group_name']} ({r['lesson_type']})")
                    with bb:
                        st.write(f"{r['cancel_date']}")
                        t_s = t_from_iso(r["start"])
                        t_e = t_from_iso(r["end"])
                        st.caption(f"{r['weekday']} {t_s}–{t_e}")
                    with cc:
                        if r["is_restored"]:
                            r_st = t_from_iso(r["restored_start"])
                            r_et = t_from_iso(r["restored_end"])
                            st.write(f"Восстановлено → **{r['restored_room_name'] or '?'}**")
                            st.caption(f"{r['restored_weekday'] or '?'} {r_st}–{r_et} (корп.{r['restored_building'] or '?'}, эт.{r['restored_floor'] or '?'})")
                        else:
                            reason = r["reason"] or "—"
                            st.write(f"Активна | Причина: {reason}")
                            st.caption(f"{r['room_name']} (корп.{r['building']}, эт.{r['floor']})")
                    with dd:
                        if st.button("X", key=f"dcn{r['id']}"):
                            delete_cancellation(r["id"])
                            st.success("Удалено")
                            st.rerun()
