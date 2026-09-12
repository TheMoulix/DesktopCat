@echo off
chcp 65001 >nul
echo ========================================================
echo Building Desktop Cat Standalone Executable (.exe)
echo ========================================================

echo [1/3] Checking requirements...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b %errorlevel%
)

echo.
echo [2/3] Compiling DesktopCat.exe with PyInstaller...
python -m PyInstaller --noconfirm --windowed --onefile ^
  --name "DesktopCat" ^
  --icon "app_icon.ico" ^
  --add-data "gif;gif" ^
  --add-data "app_icon.ico;." ^
  --hidden-import "cat_overlay_windows" ^
  --exclude-module "cat_overlay_linux" ^
  cat_overlay.pyw

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b %errorlevel%
)

echo.
echo [3/3] Packaging release directory...
if not exist "dist\DesktopCat_Release" mkdir "dist\DesktopCat_Release"
copy /Y "dist\DesktopCat.exe" "dist\DesktopCat_Release\DesktopCat.exe" >nul
xcopy /E /I /Y "gif" "dist\DesktopCat_Release\gif" >nul
xcopy /E /I /Y "gif" "dist\gif" >nul
copy /Y "README.md" "dist\DesktopCat_Release\README.md" >nul

echo.
echo ========================================================
echo [SUCCESS] DesktopCat.exe has been built!
echo Executable: dist\DesktopCat.exe
echo Standalone folder: dist\DesktopCat_Release
echo ========================================================
pause
