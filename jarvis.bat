@echo off
cd /d "%~dp0"
echo.
echo       J.A.R.V.I.S.
echo.
echo   1. Chat mode
echo   2. Voice mode
echo   3. HUD dashboard (this laptop only)
echo   4. HUD dashboard + phone (same Wi-Fi)
echo   5. My details vault (for form filling)
echo   6. Connect laptop to cloud JARVIS (agent)
echo.
set /p mode="Choose a mode (1-6): "

if "%mode%"=="1" .venv\Scripts\python main.py
if "%mode%"=="2" .venv\Scripts\python main.py --voice
if "%mode%"=="3" .venv\Scripts\python main.py --hud
if "%mode%"=="4" .venv\Scripts\python main.py --hud --lan
if "%mode%"=="5" .venv\Scripts\python main.py --vault
if "%mode%"=="6" .venv\Scripts\python main.py --agent
if not "%mode%"=="1" if not "%mode%"=="2" if not "%mode%"=="3" if not "%mode%"=="4" if not "%mode%"=="5" if not "%mode%"=="6" echo Please choose 1 to 6.
