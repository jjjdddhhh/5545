@echo off
rem setup.bat : 처음 한 번 더블클릭한다. 백엔드·화면 패키지, .env, MySQL DB와 사용자, 프롬프트를 준비한다(dev.py setup).
chcp 65001 > nul
set PYTHONUTF8=1
cd /d "%~dp0"
where python > nul 2> nul
if %errorlevel%==0 (python dev.py setup) else (py -3 dev.py setup)
pause
