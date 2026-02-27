@echo off
:: ═══════════════════════════════════════════════════════════════
:: VegaAutoclicker Launcher
:: ═══════════════════════════════════════════════════════════════

title VegaAutoclicker v2.0.0
echo.
echo  ⚡ VegaAutoclicker v2.0.0
echo  ==================================
echo.
echo  Starting development server...
echo  (Press Ctrl+C to stop)
echo.
cd /d "%~dp0"
npx tauri dev
pause
