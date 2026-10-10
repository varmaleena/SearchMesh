@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -e ".[test]"
if errorlevel 1 goto error
echo Setup complete. Open Start SearchMesh.cmd to launch.
pause
exit /b 0
:error
echo Setup failed. Check the message above. Python 3.11-3.13 and internet access are required.
pause
exit /b 1
