import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from src.config import EXCLUDED_BUILDINGS
from src.utils import d2wd, d2wt, gc, t_from_iso
from src.cancellation import (
    preview_cancel_by_teacher,
    preview_cancel_by_discipline,
    preview_cancel_single,
    apply_cancels,
    get_cancellations,
    get_active_cancellations_for_date,
    get_restored_cancellations_for_date,
    get_restored_for_date,
    find_restore_slots,
    restore_lesson,
    mass_restore,
    mass_restore_preview,
    delete_cancellation,
    get_all_teachers,
    get_all_disciplines,
)


def render():
    st.title("Отмена и восстановление занятий")
    tab_cancel, tab_restore, tab_log = st.tabs(["Отмена", "Восстановление", "Журнал"])

    with tab_cancel:
        ct = st.radio("Тип отмены:", ["По преподавателю", "По дисциплине", "Одиночная"], horizontal=True)

        if ct == "Одиночная":
            today = date.today()
            cn_single_date = st.date_input("Дата отмены:", value=today, min_value=date(2026, 1, 12), key="cn_single_date")

            wd = d2wd(cn_single_date)
            wt = d2wt(cn_single_date)

            c = gc()
            eb_ph = ",".join("?" for _ in EXCLUDED_BUILDINGS)
            rows = c.execute(f"""
                SELECT s.id, l.title || ' (' || l.lesson_type || ') — ' ||
                       g.name || ' — ' || substr(s.start,12,5) || '–' || substr(s.end,12,5) AS label
                FROM schedule s
                JOIN lessons l ON s.lesson_id = l.id
                JOIN groups g ON s.group_id = g.id
                JOIN rooms r ON s.room_id = r.id
                WHERE s.weekday = ? AND s.week_type = ?
                AND r.building NOT IN ({eb_ph})
                ORDER BY s.start, l.title
            """, (wd, wt) + tuple(EXCLUDED_BUILDINGS)).fetchall()
            c.close()

            sched_opts = {r["label"]: r["id"] for r in rows}
            sel_sched_label = st.selectbox("Занятие:", list(sched_opts.keys()), key="cn_single")
            sel_sched_id = sched_opts.get(sel_sched_label)

            cn_reason = st.text_input("Причина:", value="Болезнь преподавателя", key="cn_reason")

            if sel_sched_id:
                st.divider()
                previews = preview_cancel_single(sel_sched_id, cn_single_date)
                if previews:
                    st.info("Будет отменено: **1** занятие")
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

                    if st.button("Подтвердить отмену", type="primary", key="cn_apply_btn_single"):
                        st.session_state["confirm_cancel_single"] = True

                    if st.session_state.get("confirm_cancel_single"):
                        @st.dialog("Подтверждение отмены")
                        def _confirm_cancel_single():
                            st.warning("Подтвердить отмену занятия?")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.button("Отменить", type="primary", use_container_width=True):
                                    count = apply_cancels(previews, cn_reason)
                                    st.session_state["confirm_cancel_single"] = False
                                    st.session_state["cn_single_msg"] = f"Отменено **{count}** занятий"
                                    st.rerun()
                            with c2:
                                if st.button("Отмена", use_container_width=True):
                                    st.session_state["confirm_cancel_single"] = False
                                    st.rerun()
                        _confirm_cancel_single()

            if st.session_state.get("cn_single_msg"):
                st.success(st.session_state["cn_single_msg"])
                if st.button("Новая отмена", key="cn_new_single"):
                    st.session_state["cn_single_msg"] = None
                    st.rerun()

        else:
            ca, cb = st.columns(2)
            with ca:
                if ct == "По преподавателю":
                    teachers = get_all_teachers()
                    sel_teacher = st.selectbox("Преподаватель:", teachers, key="cn_teacher")
                elif ct == "По дисциплине":
                    disciplines = get_all_disciplines()
                    sel_disc = st.selectbox("Дисциплина:", disciplines, key="cn_disc")
            with cb:
                today = date.today()
                d1, d2 = st.columns(2)
                with d1:
                    cn_sd = st.date_input("Начало:", value=today, min_value=date(2026, 1, 12), key="cn_sd")
                with d2:
                    cn_ed = st.date_input("Конец:", value=cn_sd + timedelta(days=13), min_value=cn_sd, key="cn_ed")
                cn_reason = st.text_input("Причина:", value="Болезнь преподавателя", key="cn_reason")

            st.divider()

            if st.button("Предпросмотр", type="primary", key="cn_preview_btn"):
                if ct == "По преподавателю":
                    previews = preview_cancel_by_teacher(sel_teacher, cn_sd, cn_ed)
                else:
                    previews = preview_cancel_by_discipline(sel_disc, cn_sd, cn_ed)
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
                    st.session_state["confirm_cancel_multi"] = True

                if st.session_state.get("confirm_cancel_multi"):
                    @st.dialog("Подтверждение отмены")
                    def _confirm_cancel_multi():
                        st.warning(f"Подтвердить отмену **{len(previews)}** занятий?")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Отменить", type="primary", use_container_width=True):
                                count = apply_cancels(previews, cn_reason)
                                st.session_state["confirm_cancel_multi"] = False
                                st.session_state["cn_previews"] = []
                                st.session_state["cn_msg"] = f"Отменено **{count}** занятий"
                                st.rerun()
                        with c2:
                            if st.button("Отмена", use_container_width=True):
                                st.session_state["confirm_cancel_multi"] = False
                                st.rerun()
                    _confirm_cancel_multi()

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
                            st.session_state["confirm_restore"] = True

                        if st.session_state.get("confirm_restore"):
                            @st.dialog("Подтверждение восстановления")
                            def _confirm_restore():
                                st.warning(f"Восстановить **{len(has_slots)}** занятий?")
                                c1, c2 = st.columns(2)
                                with c1:
                                    if st.button("Восстановить", type="primary", use_container_width=True):
                                        cids_to_restore = [p["cancel_id"] for p in has_slots]
                                        with st.spinner("Восстановление..."):
                                            result = mass_restore(cids_to_restore)
                                        st.session_state["confirm_restore"] = False
                                        st.session_state["rs_mass_result"] = result
                                        st.session_state["rs_mass_pv"] = None
                                        st.rerun()
                                with c2:
                                    if st.button("Отмена", use_container_width=True):
                                        st.session_state["confirm_restore"] = False
                                        st.rerun()
                            _confirm_restore()

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


render()
