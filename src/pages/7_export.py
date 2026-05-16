import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from src.export import get_all_groups, get_schedule_for_group, get_schedule_for_teacher, generate_excel
from src.cancellation import get_all_teachers


def render():
    st.title("Экспорт расписания")

    et = st.radio("Экспорт для:", ["Группы", "Преподавателя"], horizontal=True)

    if et == "Группы":
        groups = get_all_groups()
        sel = st.selectbox("Выберите группу:", groups, key="exp_group")
        if st.button("Сформировать Excel", type="primary", use_container_width=True):
            grid = get_schedule_for_group(sel)
            st.session_state["exp_data"] = generate_excel(grid, title=sel)
            st.session_state["exp_fname"] = f"schedule_{sel}.xlsx"
    else:
        teachers = get_all_teachers()
        sel = st.selectbox("Выберите преподавателя:", teachers, key="exp_teacher")
        if st.button("Сформировать Excel", type="primary", use_container_width=True):
            grid = get_schedule_for_teacher(sel)
            st.session_state["exp_data"] = generate_excel(grid, title=sel)
            st.session_state["exp_fname"] = f"schedule_{sel}.xlsx"

    if "exp_data" in st.session_state:
        st.download_button(
            label="Скачать файл",
            data=st.session_state["exp_data"],
            file_name=st.session_state["exp_fname"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


render()
