@echo off
rem Build a standalone dist\esl_ap_gui.exe (no Python needed on the target PC).
rem Run from a Windows command prompt in this directory.
setlocal
cd /d "%~dp0"

if not exist .venv-win (
    py -3 -m venv .venv-win || goto :error
)
call .venv-win\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt pyinstaller || goto :error

pyinstaller --noconfirm --onefile --windowed --name esl_ap_gui esl_ap_gui.py || goto :error

echo.
echo Built dist\esl_ap_gui.exe
exit /b 0

:error
echo Build failed.
exit /b 1
