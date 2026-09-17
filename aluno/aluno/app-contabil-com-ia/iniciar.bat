@echo off
python "%~dp0scripts\local.py" --start
if errorlevel 1 (
  pause
  exit /b 1
)
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "$s=Get-Content -Raw '%~dp0.runtime\estado.json' | ConvertFrom-Json; if ($s.url) {$s.url}"`) do start "App Contábil" "%%U"
