import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from src.utils import gc, slot_label, t_from_iso, del_transfer, del_booking
from src.cancellation import get_cancellations, delete_cancellation


def render():
    st.title("Управление переносами и бронированиями")
    t1, t2, t3 = st.tabs(["Переносы", "Бронирования", "Отмены"])

    with t1:
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

            trs = [x for x in trs_list
                   if (not sel_dates or x["booking_date"] in sel_dates)
                   and (not sel_subjects or x["lesson_title"] in sel_subjects)
                   and (not sel_rooms or x["old_room"] in sel_rooms)
                   and (not sel_groups or any(g in sel_groups for g in x["groups"]))]

            total_db_records = sum(len(x["ids"]) for x in trs_list)
            shown_records = sum(len(x["ids"]) for x in trs)

            st.divider()
            col_show, col_del = st.columns([3, 1])
            with col_show:
                st.info(f"Показано: **{len(trs)}** переносов ({shown_records} записей в БД)")
            with col_del:
                if st.button("Удалить ВСЕ переносы", type="secondary", key="del_all_transfers"):
                    st.session_state["confirm_del_all_transfers"] = True

                if st.session_state.get("confirm_del_all_transfers"):
                    @st.dialog("Подтверждение удаления")
                    def _confirm_del_all_transfers():
                        st.warning("Вы уверены, что хотите удалить **все** переносы?")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Удалить", type="primary", use_container_width=True):
                                c = gc()
                                c.execute("DELETE FROM transfers")
                                c.commit()
                                c.close()
                                st.session_state["confirm_del_all_transfers"] = False
                                st.success("Удалены все переносы!")
                                st.rerun()
                        with c2:
                            if st.button("Отмена", use_container_width=True):
                                st.session_state["confirm_del_all_transfers"] = False
                                st.rerun()
                    _confirm_del_all_transfers()

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
                    st.session_state["confirm_del_all_bookings"] = True

                if st.session_state.get("confirm_del_all_bookings"):
                    @st.dialog("Подтверждение удаления")
                    def _confirm_del_all_bookings():
                        st.warning("Вы уверены, что хотите удалить **все** бронирования?")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Удалить", type="primary", use_container_width=True):
                                c = gc()
                                c.execute("DELETE FROM event_bookings")
                                c.commit()
                                c.close()
                                st.session_state["confirm_del_all_bookings"] = False
                                st.success(f"Удалено все {len(bks_all)} бронирований!")
                                st.rerun()
                        with c2:
                            if st.button("Отмена", use_container_width=True):
                                st.session_state["confirm_del_all_bookings"] = False
                                st.rerun()
                    _confirm_del_all_bookings()
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

                if filtered and len(filtered) < len(all_cancels):
                    if st.button("Удалить отфильтрованные", type="secondary", key="del_filtered_cancels"):
                        for r in filtered:
                            delete_cancellation(r["id"])
                        st.success(f"Удалено {len(filtered)} отмен!")
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


render()
