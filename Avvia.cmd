@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 moodle_downloader.py
) else (
    python moodle_downloader.py
)
if errorlevel 1 (
    echo.
    echo Avvio non riuscito. Serve Python 3.10 o successivo con Tkinter.
    pause
)
