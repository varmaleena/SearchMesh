@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run Setup SearchMesh.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m searchmesh.cli serve --mode fixture --open
pause

