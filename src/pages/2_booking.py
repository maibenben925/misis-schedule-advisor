import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from datetime import date, datetime as dt

from src.utils import d2wd, d2wt, to_iso, check_booking_conflict, save_booking
from src.search_engine import find_room_for_event


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
    wt_label = "Верхняя неделя" if p_wt == "upper" else "Нижняя неделя" if p_wt else ""

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


def render():
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
        sel_date = st.date_input("Дата:", value=today, min_value=today, key="b_date")
        wd = d2wd(sel_date)
        wt = d2wt(sel_date)
        wt_label = "Верхняя неделя" if wt == "upper" else "Нижняя неделя"
        st.caption(f"{wd} ({wt_label})")
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


render()
