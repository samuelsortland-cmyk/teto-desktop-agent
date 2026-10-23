@echo off
REM Teto Desktop Agent - double-click me. The first run sets everything up
REM (installs Python if needed, ~2-5 minutes); later runs start Teto instantly.
setlocal
cd /d "%~dp0"
title Teto setup

REM ---- find (or install) Python 3.10+
set "PY="
for %%V in (313 312 311 310) do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)
if not defined PY (
    where py >nul 2>nul && py -3 -c "import sys,tkinter; sys.exit(sys.version_info < (3,10))" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    where winget >nul 2>nul || goto :nopython
    echo Installing Python for Teto ^(one time only^)...
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY goto :nopython

REM ---- private environment + packages (re-installed only when requirements change)
if not exist ".venv\Scripts\python.exe" (
    echo Setting up Teto...
    %PY% -m venv .venv || goto :nopython
)
".venv\Scripts\python.exe" -c "import tkinter" 2>nul || goto :notk
fc /b requirements.txt ".venv\installed.txt" >nul 2>nul
if errorlevel 1 (
    echo Downloading Teto's brain ^(Claude Code^) and helpers - this takes a minute...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :piperr
    copy /y requirements.txt ".venv\installed.txt" >nul
    powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcut.ps1" -AppDir "%CD%" >nul 2>nul
    echo Done! A "Teto" shortcut was added to your desktop and Start menu.
)

start "" ".venv\Scripts\pythonw.exe" "%CD%\main.py"
exit /b 0

:nopython
echo.
echo Teto needs Python 3.10 or newer and couldn't install it automatically.
echo Get it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then double-click START-TETO.bat again.
pause
exit /b 1

:notk
echo.
echo Your Python is missing tkinter. Re-run the Python installer, choose Modify,
echo enable "tcl/tk and IDLE", then double-click START-TETO.bat again.
pause
exit /b 1

:piperr
echo.
echo Downloading Teto's parts failed. Check your internet connection and try again.
pause
exit /b 1
