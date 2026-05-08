@echo off
chcp 65001 >nul 2>&1
echo ================================
echo  Обновление БД расписания
echo ================================
echo.
echo  Текущая БД будет удалена и пересоздана из API.
echo  Все переносы и бронирования будут потеряны!
echo.

cd /d "%~dp0"

set /p CONFIRM="Продолжить? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Отменено.
    pause
    exit /b 0
)

if exist data\schedule.db del data\schedule.db

if exist .venv (
    .venv\Scripts\python.exe pipeline\build_db.py
) else (
    python pipeline\build_db.py
)

echo.
pause
