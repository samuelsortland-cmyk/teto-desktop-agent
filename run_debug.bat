@echo off
REM Same as START-TETO.bat but keeps a console open so you can see any errors.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call START-TETO.bat
".venv\Scripts\python.exe" main.py --selftest
".venv\Scripts\python.exe" main.py
pause
