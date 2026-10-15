@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist "..\.venv\Scripts\uvicorn.exe" (
  echo Missing .venv. See README.md.
  exit /b 1
)
"..\.venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000 --reload
