import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from src.utils import gc, get_rooms, get_buildings, get_affected, d2wd, d2wt, save_transfers, slot_label, t_from_iso
from src.search_engine import get_lessons_info_batch
from src.optimization import mass_reallocate


def render():
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
            sd = st.date_input("Начало:", value=today, min_value=today, key="inc_sd")
        with d2:
            ed = st.date_input("Конец:", value=sd + timedelta(days=4), min_value=sd, key="inc_ed")

    st.divider()

    if st.session_state.get("saved_msg"):
        st.success(st.session_state["saved_msg"])
        if st.button("Новый перенос"):
            st.session_state["saved_msg"] = None
            st.session_state["ir"] = None
            st.session_state["ir_sd"] = None
            st.session_state["ir_ed"] = None
            st.rerun()
        st.divider()

    aff, current_room_overrides = get_affected(sids_in, sd, ed) if sids_in else ([], {})

    if st.button("Сгенерировать замены", type="primary", disabled=len(aff) == 0):
        with st.spinner("Оптимизация..."):
            _excl = set(sids_in)
            c_evac = gc()
            evacuated = c_evac.execute("""
                SELECT DISTINCT old_room_id FROM transfers
                WHERE booking_date >= ? AND booking_date <= ?
            """, (str(sd), str(ed))).fetchall()
            c_evac.close()
            for r in evacuated:
                _excl.add(r["old_room_id"])
            c_inc = gc()
            incident_rooms = c_inc.execute("""
                SELECT DISTINCT ir.room_id FROM incident_rooms ir
                JOIN incidents i ON ir.incident_id = i.id
                WHERE i.start_date <= ? AND i.end_date >= ?
            """, (str(ed), str(sd))).fetchall()
            c_inc.close()
            for r in incident_rooms:
                _excl.add(r["room_id"])
            st.session_state["ir"] = mass_reallocate([r["id"] for r in aff], excluded_room_ids=list(_excl), current_room_overrides=current_room_overrides)
            st.session_state["ir_sd"] = sd
            st.session_state["ir_ed"] = ed
            st.session_state["ir_excl"] = list(_excl)
            st.session_state["ir_overrides"] = current_room_overrides

    res = st.session_state.get("ir")
    if res:
        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Перенесено", len(res.assignments))
        m2.metric("Не хватило", len(res.unassigned))
        m3.metric("Средний штраф", f"{res.avg_penalty:.1f}")
        m4.metric("Средний Match", f"{res.avg_match_percent:.1f}%")
        if res.assignments:
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

            info_cache = get_lessons_info_batch(list(res.assignments.keys()))

            slot_groups: dict[tuple, list[tuple]] = {}
            for sid in res.assignments:
                info = info_cache.get(sid)
                if info is None:
                    continue
                dk = (info["lesson_id"], info["weekday"], info["start"], info["end"])
                slot_groups.setdefault(dk, []).append(sid)

            lesson_display = {}
            for display_key, sids_for_slot in slot_groups.items():
                first_sid = sids_for_slot[0]
                info = info_cache[first_sid]
                s = res.assignments[first_sid]
                lid = info["lesson_id"]
                wt_key = (info["weekday"], info["start"], info["end"], info["week_type"])
                n_dates = date_groups.get(wt_key, 1)
                bdate = date_map.get(first_sid, "")
                t_start = info["start"][11:16] if len(info["start"]) > 5 else info["start"]
                t_end = info["end"][11:16] if len(info["end"]) > 5 else info["end"]

                total_st = sum(info_cache[s2]["students_count"] for s2 in sids_for_slot)
                n_groups = len(sids_for_slot)
                need_proj = any(info_cache[s2]["needs_projector"] for s2 in sids_for_slot)
                need_comp = any(info_cache[s2]["needs_computers"] for s2 in sids_for_slot)

                req_parts = []
                req_parts.append(f"{total_st} чел.")
                if n_groups > 1:
                    req_parts[0] += f" ({n_groups} гр.)"
                if need_proj:
                    req_parts.append("проектор")
                if need_comp:
                    req_parts.append("компьютеры")

                lesson_display[display_key] = {
                    "Время": slot_label(t_start, t_end),
                    "Тип": info["lesson_type"],
                    "Предмет": info["lesson_title"],
                    "Группы": [info_cache[s2]["group_name"] for s2 in sids_for_slot],
                    "Было": info["room_name"],
                    "Стало": f"{s.name} (корп.{s.building}, эт.{s.floor})",
                    "Штраф": s.penalty,
                    "%": f"{s.match_percent}%",
                    "n_dates": n_dates,
                    "first_date": bdate,
                    "Требования": " ".join(req_parts),
                }

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
            st.caption(f"«Требования»: кол-во студентов, проектор, компьютеры. «Дни» — первая дата попадания в верхнюю и нижнюю неделю.")
            st.caption(f"Формула штрафа: разные корпуса +100, этаж ×5, лишние места ×1, ненужные компьютеры +10, ненужный проектор +5")
            if st.button("Сохранить замены", type="primary"):
                st.session_state["confirm_save_transfers"] = True

            if st.session_state.get("confirm_save_transfers"):
                @st.dialog("Подтверждение сохранения")
                def _confirm_save_transfers():
                    st.warning("Сохранить переносы в расписание?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Сохранить", type="primary", use_container_width=True):
                            ir_sd = st.session_state.get("ir_sd", sd)
                            ir_ed = st.session_state.get("ir_ed", ed)
                            count = save_transfers(res.assignments, date_map, ir_sd, ir_ed, excluded_room_ids=list(st.session_state.get("ir_excl", [])), current_room_overrides=st.session_state.get("ir_overrides", {}))
                            st.session_state["confirm_save_transfers"] = False
                            st.session_state["saved_msg"] = f"Успешно сохранено **{count}** переносов!"
                            st.session_state["ir"] = None
                            st.session_state["ir_sd"] = None
                            st.session_state["ir_ed"] = None
                            st.rerun()
                    with c2:
                        if st.button("Отмена", use_container_width=True):
                            st.session_state["confirm_save_transfers"] = False
                            st.rerun()
                _confirm_save_transfers()
        if res.unassigned:
            st.subheader("Не хватило")

            _sd = st.session_state.get("ir_sd", sd)
            _ed = st.session_state.get("ir_ed", ed)

            def _first_date(weekday: str, week_type: str, start_d: date, end_d: date) -> str:
                d = start_d
                while d <= end_d:
                    if d2wd(d) == weekday and d2wt(d) == week_type:
                        return str(d)
                    d += timedelta(days=1)
                return str(start_d)

            ua = []
            for detail in res.unassigned_details:
                dd = _first_date(detail["weekday"], detail["week_type"], _sd, _ed)
                req_parts = [f"{detail['students_count']} чел."]
                if detail["needs_projector"]:
                    req_parts.append("проектор")
                if detail["needs_computers"]:
                    req_parts.append("компьютеры")
                group_display = detail["group_name"]
                n_groups = len(detail["schedule_ids"])
                if n_groups > 1:
                    group_display = f"{group_display} ({n_groups} гр.)"
                ua.append({
                    "Дата": dd,
                    "День": detail["weekday"],
                    "Время": slot_label(t_from_iso(detail["start"]), t_from_iso(detail["end"])),
                    "Тип": detail["lesson_type"],
                    "Предмет": detail["lesson_title"],
                    "Группа": group_display,
                    "Требования": ", ".join(req_parts),
                    "Причина": detail["reason"],
                })
            st.dataframe(pd.DataFrame(ua), width="stretch", hide_index=True)


render()
