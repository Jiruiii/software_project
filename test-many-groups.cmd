@echo off
cd /d "%~dp0"
python tests\run_many_groups.py
echo.
if errorlevel 1 (echo Test failed. See output\playwright\many-groups-report.json) else (echo All tests passed. See output\playwright\many-groups-report.json)
pause
