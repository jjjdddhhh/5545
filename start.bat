@echo off
rem start.bat : 더블클릭하면 백엔드(8000)와 화면(5173)을 함께 켜고 브라우저를 연다. 끌 때는 이 창에서 Ctrl+C를 누른다(dev.py start).
chcp 65001 > nul
set PYTHONUTF8=1
cd /d "%~dp0"
where python > nul 2> nul
if %errorlevel%==0 (python dev.py start) else (py -3 dev.py start)
pause
