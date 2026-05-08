@echo off
chcp 1251 >nul 2>&1
echo ================================
echo  Расписание МИСИС — Запуск
echo ================================
echo.

cd /d "%~dp0"

:: [1] Виртуальное окружение
if not exist .venv (
    echo [1/4] Создание виртуального окружения...
    python -m venv .venv
    if errorlevel 1 (
        echo ОШИБКА: не удалось создать .venv
        echo Установите Python 3.12+: https://python.org
        pause
        exit /b 1
    )
) else (
    echo [1/4] Виртуальное окружение OK
)

:: [2] Зависимости
echo [2/4] Установка зависимостей...
.venv\Scripts\pip.exe install -r requirements.txt -q
if errorlevel 1 (
    echo ОШИБКА: не удалось установить зависимости
    pause
    exit /b 1
)

:: [3] БД — создать, если нет
if not exist data\schedule.db (
    echo [3/4] БД не найдена — генерация из API...
    echo         (это может занять 2-3 минуты)
    .venv\Scripts\python.exe pipeline\build_db.py
    if errorlevel 1 (
        echo ОШИБКА: не удалось создать БД
        echo Проверьте интернет-соединение и запустите вручную:
        echo   python pipeline\build_db.py
        pause
        exit /b 1
    )
) else (
    echo [3/4] БД OK
)

:: [4] Запуск
echo [4/4] Запуск Streamlit...
echo.
echo  Приложение: http://localhost:8502
echo  Остановить:  Ctrl+C
echo.
.venv\Scripts\python.exe -m streamlit run src\app.py --server.headless true --server.port 8502
pause
