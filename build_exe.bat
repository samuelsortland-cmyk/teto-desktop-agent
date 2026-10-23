@echo off
REM Builds a standalone Teto (no Python needed on the target PC) into dist\Teto
REM and zips it as dist\Teto-Windows.zip.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run START-TETO.bat once first to set up the environment.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pyinstaller || exit /b 1
REM Remember which code is baked in, so the self-updater later fetches only what changed
".venv\Scripts\python.exe" -c "from teto.updater import write_build_manifest; write_build_manifest('.', r'assets\build_manifest.json')" || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --name Teto --icon assets\teto.ico --add-data "assets;assets" ^
    --collect-all claude_agent_sdk --collect-all playwright --collect-all uiautomation ^
    --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 ^
    --hidden-import pynput._util.win32 --hidden-import pynput._util.win32_vks --hidden-import six ^
    main.py || (pause & exit /b 1)
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\Teto -DestinationPath dist\Teto-Windows.zip"
echo.
echo Done! Unzip dist\Teto-Windows.zip anywhere and double-click Teto.exe
pause
