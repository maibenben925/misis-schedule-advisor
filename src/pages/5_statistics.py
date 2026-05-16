import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd

from src.stats import fund_summary_with_transfers, room_load_stats, load_by_slot


def render():
    st.title("Статистика аудиторного фонда")

    fs = fund_summary_with_transfers()
    rl = room_load_stats()

    st.subheader("Сводка по аудиторному фонду")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Аудиторий", fs["rooms"])
    m2.metric("Корпусов", fs["buildings"])
    m3.metric("Учебных групп", fs["groups"])
    m4.metric("Средняя вместимость", f'{fs["avg_capacity"]} мест')
    m5.metric("Переносов", fs["transfers"])

    m6, m7, m8, m9, m10 = st.columns(5)
    m6.metric("Возможных слотов", fs["total_slots"])
    m7.metric("Занято слотов", fs["occupied_slots"])
    m8.metric("Загрузка фонда", f'{fs["load_pct"]}%')
    m9.metric("Бронирований", fs["bookings"])
    m10.metric("Отменённых занятий", fs["cancellations"])

    st.subheader("Наиболее и наименее загруженные аудитории")
    st.caption(
        f"Загрузка = занятые слоты / 84 возможных (6 дней × 7 пар × 2 недели). "
        f"Средняя загрузка по фонду: **{rl['avg_load']}%**. "
        f"Пустых аудиторий: {rl['empty_rooms']} из {rl['total_rooms']}."
    )

    ml_tab, ll_tab = st.tabs(["Наиболее загруженные", "Наименее загруженные"])

    with ml_tab:
        if rl["most_loaded"]:
            ml_df = pd.DataFrame([{
                "Аудитория": r["name"],
                "Корпус": r["building"],
                "Вместимость": r["capacity"],
                "ПК": "Да" if r["has_computers"] else "Нет",
                "Занято слотов": r["occupied_slots"],
                "Загрузка": f'{r["load_pct"]}%',
            } for r in rl["most_loaded"]])
            st.dataframe(ml_df, width="stretch", hide_index=True)
        else:
            st.info("Нет данных по загруженности.")

    with ll_tab:
        if rl["least_loaded"]:
            ll_df = pd.DataFrame([{
                "Аудитория": r["name"],
                "Корпус": r["building"],
                "Вместимость": r["capacity"],
                "ПК": "Да" if r["has_computers"] else "Нет",
                "Занято слотов": r["occupied_slots"],
                "Загрузка": f'{r["load_pct"]}%',
            } for r in rl["least_loaded"]])
            st.dataframe(ll_df, width="stretch", hide_index=True)
        else:
            st.info("Нет данных по загруженности.")

    st.subheader("Загрузка по парам")
    st.caption("% занятых аудиторий для каждого дня и пары (берётся более загруженная неделя).")
    ls = load_by_slot()
    if ls:
        weekdays = []
        seen = set()
        for r in ls:
            if r["weekday"] not in seen:
                weekdays.append(r["weekday"])
                seen.add(r["weekday"])
        slots = sorted(set(r["slot"] for r in ls), key=lambda s: int(s[0]))

        matrix = {}
        for r in ls:
            matrix[(r["weekday"], r["slot"])] = r["load_pct"]

        header = "<table style='width:100%;border-collapse:collapse;text-align:center;font-size:14px'>"
        header += "<tr><th style='border:1px solid #ddd;padding:6px;background:#f0f0f0'>День / Пара</th>"
        for sl in slots:
            header += f"<th style='border:1px solid #ddd;padding:6px;background:#f0f0f0'>{sl}</th>"
        header += "</tr>"

        for wd in weekdays:
            header += f"<tr><td style='border:1px solid #ddd;padding:6px;font-weight:bold;background:#f9f9f9'>{wd}</td>"
            for sl in slots:
                pct = matrix.get((wd, sl), 0)
                if pct >= 70:
                    bg = "#fee2e2"
                elif pct >= 40:
                    bg = "#fef3c7"
                else:
                    bg = "#d1fae5"
                header += f"<td style='border:1px solid #ddd;padding:6px;background:{bg}'>{pct}%</td>"
            header += "</tr>"
        header += "</table>"
        st.markdown(header, unsafe_allow_html=True)
    else:
        st.info("Нет данных.")


render()
