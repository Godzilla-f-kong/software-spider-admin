@echo off
setlocal
cd /d "%~dp0..\admin-web"
if not exist "node_modules\.bin\vite.cmd" (
  echo Missing node_modules. Run npm install in admin-web.
  exit /b 1
)
npm run dev
