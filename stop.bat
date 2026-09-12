@echo off
chcp 65001 >nul
taskkill /F /IM DesktopCat.exe >nul 2>&1
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq Desktop Cat Overlay" >nul 2>&1
set "LOCK_FILE=%~dp0.cat_instance.lock"
if exist "%LOCK_FILE%" del /F /Q "%LOCK_FILE%" >nul 2>&1
set "DIST_LOCK_FILE=%~dp0dist\.cat_instance.lock"
if exist "%DIST_LOCK_FILE%" del /F /Q "%DIST_LOCK_FILE%" >nul 2>&1
echo Desktop Cat closed!
ping -n 2 127.0.0.1 >nul
exit
