@echo off
title LogiBatteryWidget - Autostart AUS
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "LogiBatteryWidget" /f
echo Autostart deaktiviert.
pause
