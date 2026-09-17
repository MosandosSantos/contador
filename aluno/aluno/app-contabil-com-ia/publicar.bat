@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0scripts\empacotar_publicacao.py"
pause
