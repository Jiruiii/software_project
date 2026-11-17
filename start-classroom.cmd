@echo off
setlocal
cd /d "%~dp0"
python -c "import sys, sqlite3; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 (
    python app.py %*
    goto :done
)
py -3 -c "import sys, sqlite3; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 (
    py -3 app.py %*
    goto :done
)
echo Python 3.11 or later is required. Install Python with the Python launcher enabled.
echo https://www.python.org/downloads/windows/
:done
pause
