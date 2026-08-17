@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" backend\manual_test.py
echo.
echo ============================================
echo Test finished. Press any key to close this window.
echo ============================================
pause >nul
