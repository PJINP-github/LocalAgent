@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-kurama.ps1"
if errorlevel 1 (
    echo.
    echo [启动失败] pwsh 返回错误码 %errorlevel%
    pause
)