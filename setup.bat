@echo off
chcp 65001 >nul
echo ========================================================
echo Installing Desktop Cat dependencies...
echo ========================================================
python -m pip install -r requirements.txt
if %errorlevel% equ 0 (
    echo.
    echo [SUCCESS] Dependencies installed successfully!
    echo Run start.bat to launch the cat.
) else (
    echo.
    echo [ERROR] Failed to install dependencies. Check if Python is installed.
)
pause
