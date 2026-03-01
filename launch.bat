@echo off
:: ═══════════════════════════════════════════════════════════════
:: Antigravity Autoclicker Launcher
:: ═══════════════════════════════════════════════════════════════

title Antigravity Autoclicker v2.0.0
echo.
echo  ⚡ Antigravity Autoclicker v2.0.0
echo  ==================================
echo.
echo  Starting development server...
echo  (Press Ctrl+C to stop)
echo.
cd /d "%~dp0"
npx tauri dev
pause
