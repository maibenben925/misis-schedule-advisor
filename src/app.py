import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from src.config import DB_PATH
from src.utils import ensure_tables, init_incidents_table
from src.cancellation import ensure_cancellations_table

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

ensure_tables()
ensure_cancellations_table()
init_incidents_table()

incidents = st.Page("pages/1_incidents.py", title="Инциденты", default=True)
booking = st.Page("pages/2_booking.py", title="Бронирование")
cancellation = st.Page("pages/3_cancellation.py", title="Отмена занятий")
schedule = st.Page("pages/4_schedule.py", title="Расписание")
statistics = st.Page("pages/5_statistics.py", title="Статистика")
management = st.Page("pages/6_management.py", title="Управление")
export = st.Page("pages/7_export.py", title="Экспорт")

pg = st.navigation([incidents, booking, cancellation, schedule, statistics, management, export])
pg.run()
