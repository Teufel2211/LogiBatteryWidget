@echo off
title LogiBatteryWidget - Autostart AN
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "LogiBatteryWidget" /t REG_SZ /d "\"%~dp0..\LogiBatteryWidget.exe\"" /f
echo Autostart aktiviert auf LogiBatteryWidget.exe
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "LogiBatteryWidget"
pause
