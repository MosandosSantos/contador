@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto erro
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erro
echo Ambiente Python preparado. Execute iniciar.bat.
pause
exit /b 0
:erro
echo A preparacao falhou. Verifique a mensagem acima.
pause
exit /b 1
