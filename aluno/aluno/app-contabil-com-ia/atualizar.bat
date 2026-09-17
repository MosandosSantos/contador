@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0scripts\atualizar_selecionar.py"
pause
