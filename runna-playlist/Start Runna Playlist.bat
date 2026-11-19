@echo off
rem Windows: double-click to start. First run installs everything (needs Python 3.10+ from python.org, "Add to PATH" ticked).
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\runna-playlist.exe" (
  echo First run: setting things up ^(about a minute^)...
  %PY% -m venv .venv || goto fail
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -e ".[ytmusic]" || goto fail
)
".venv\Scripts\runna-playlist.exe"
goto :eof
:fail
echo Setup failed - is Python 3.10+ installed from python.org? See the messages above.
pause
