@echo off
title LogiBatteryWidget
cd /d "%~dp0.."
echo Installiere Abhaengigkeiten...
python -m pip install -r requirements.txt
echo.
echo Starte Widget...
python src\app.py
pause
