@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:loop
cls
echo ==============================================
echo   codeLook.py  -  project snapshot packer
echo ==============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    goto :wait
)

python -c "import yaml" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing PyYAML...
    python -m pip install pyyaml
    if errorlevel 1 (
        echo [ERROR] PyYAML install failed. Run: pip install pyyaml
        goto :wait
    )
)

if not exist "look.yaml" (
    echo [ERROR] look.yaml not found next to run.bat.
    goto :wait
)

set "SEG_DIR=%~dp0segments"
if exist "%SEG_DIR%\*.txt" (
    echo [CLEAN] removing old segments...
    del /q "%SEG_DIR%\*.txt" >nul 2>nul
    if errorlevel 1 (
        echo [CLEAN] WARN: some files locked, delete manually.
    ) else (
        echo [CLEAN] done.
    )
) else (
    echo [CLEAN] no old segments, skip.
)
echo.

python codeLook.py %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [OK] snapshot generated.
    echo Output dir: %SEG_DIR%
    echo.
    dir /b "%SEG_DIR%\seg-*.txt" 2>nul
) else (
    echo [ERROR] snapshot failed. See log above.
)

:wait
echo.
echo ==============================================
echo   ENTER = run again     Q = quit
echo ==============================================
set "CHOICE="
set /p "CHOICE=Prompt: "
if /i "%CHOICE%"=="Q"    goto :eof
if /i "%CHOICE%"=="QUIT" goto :eof
goto loop