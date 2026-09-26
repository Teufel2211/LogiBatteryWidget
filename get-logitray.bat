@echo off
title LogiBatteryWidget - logitray herunterladen
echo Lade logitray.exe (HID Direktabfrage ohne G HUB, von Ithilias/logitray)...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/Ithilias/logitray/releases/download/v0.4.0/logitray.exe' -OutFile '%~dp0logitray.exe'"
if exist "%~dp0logitray.exe" (
  echo Fertig: logitray.exe liegt im Programmordner.
) else (
  echo FEHLER: Download fehlgeschlagen.
)
pause
