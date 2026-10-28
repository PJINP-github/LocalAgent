@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-kurama.ps1"
if errorlevel 1 (
    echo.
    echo [启动失败] 错误码 %errorlevel%
    pause
)