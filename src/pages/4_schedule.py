import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from datetime import date

from src.config import SLOTS
from src.utils import gc, get_rooms, get_buildings, get_sched_for_date, get_transfers_for_date, t2m, t_from_iso
from src.cancellation import get_active_cancellations_for_date, get_restored_cancellations_for_date, get_restored_for_date


def render():
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
    restored_cancels = get_restored_cancellations_for_date(sel_date)
    cancel_sids = set(r["schedule_id"] for r in active_cancels)
    restored_cancel_sids = set(r["schedule_id"] for r in restored_cancels)
    cancel_map = {}
    for r in active_cancels:
        cancel_map[(r["room_id"], r["start"][11:16] if len(r["start"]) > 5 else r["start"])] = r
    restored_cancel_map = {}
    for r in restored_cancels:
        k = (r["room_id"], r["start"][11:16] if len(r["start"]) > 5 else r["start"])
        if k not in restored_cancel_map:
            restored_cancel_map[k] = {"row": r, "group_names": [r["group_name"]]}
        else:
            restored_cancel_map[k]["group_names"].append(r["group_name"])

    restored_rows = get_restored_for_date(sel_date)
    restored_map = {}
    for r in restored_rows:
        k = (r["room_id"], r["start"][11:16] if len(r["start"]) > 5 else r["start"])
        if k not in restored_map:
            restored_map[k] = {"row": r, "group_names": [r["group_name"]]}
        else:
            restored_map[k]["group_names"].append(r["group_name"])

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
    c = gc()
    bk_rows = c.execute("""
        SELECT eb.id as bid,eb.event_name,eb.organizer,eb.attendees_count,eb.booking_date,
               eb.room_id,substr(eb.start,12,5) as st,substr(eb.end,12,5) as et
        FROM event_bookings eb WHERE eb.booking_date=?
    """, (str(sel_date),)).fetchall()
    c.close()
    for bk in bk_rows:
        abk.setdefault(bk["room_id"], []).append(bk)

    sm = {}
    for r in sg:
        sm[(r["room_id"], r["start"])] = r

    sel_wt_label = "Верхняя неделя" if sel_wt == "upper" else "Нижняя неделя"
    st.subheader(f"{sel_date.strftime('%d.%m.%Y')} — {sel_wd} ({sel_wt_label})")

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
                re = restored_entry["row"]
                gn = ", ".join(sorted(set(restored_entry["group_names"])))
                cell = (
                    f'<div style="font-weight:bold;color:#5b21b6;">🔄 {re["lesson_title"]}</div>'
                    f'<div style="font-size:9px;">{re["lesson_type"]}<br>{gn}</div>'
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
                elif any(x in restored_cancel_sids for x in sc["sids"]):
                    rc_info = restored_cancel_map.get((rm["id"], s))
                    rc = rc_info["row"] if rc_info else None
                    rc_gn = ", ".join(sorted(set(rc_info["group_names"]))) if rc_info else sc["gd"]
                    restore_str = ""
                    if rc and rc["restored_room_name"]:
                        restore_str = f'<div style="font-size:8px;color:#5b21b6;">→ Восстановлено: {rc["restored_weekday"]} {rc["restored_start"]}–{rc["restored_end"]} ({rc["restored_room_name"]})</div>'
                    cell = (
                        f'<div style="font-weight:bold;color:#6b7280;text-decoration:line-through;">🚫 {sc["lesson_title"]}</div>'
                        f'<div style="font-size:9px;color:#9ca3af;">{sc["lesson_type"]} | {rc_gn}</div>'
                        f'{restore_str}'
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
                        f'<div style="font-size:9px;">{bkk["organizer"]} | {bkk["attendees_count"]} чел.</div>'
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


render()
