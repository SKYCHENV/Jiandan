@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "VENV_PYTHONW=%CD%\.venv\Scripts\pythonw.exe"

if exist "%VENV_PYTHONW%" goto launch

echo [Jiandan] Preparing the local Python environment...
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)

if not exist "%VENV_PYTHON%" goto setup_failed
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto setup_failed
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

:launch
start "" "%VENV_PYTHONW%" -m jy_live_paste gui
exit /b 0

:setup_failed
echo.
echo [Jiandan] Setup failed. Install Python 3.10 or newer and try again.
pause
exit /b 1
