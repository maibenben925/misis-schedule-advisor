@echo off
echo ================================
echo  Запуск приложения расписания
echo ================================
echo.

cd /d "%~dp0"

if not exist .venv (
    echo [1/2] Создание виртуального окружения...
    python -m venv .venv
)

echo [2/2] Запуск Streamlit...
.venv\Scripts\python.exe -m streamlit run src\app.py --server.headless true --server.port 8502
pause
