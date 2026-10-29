@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
if exist "..\..\venv\Scripts\python.exe" set "PY=..\..\venv\Scripts\python.exe"

:menu
cls
echo ==============================================
echo   Kurama Tools
echo ==============================================
echo   Python : %PY%
echo.
echo   [1] fix-once.py --check      status check only
echo   [2] fix-once.py --dry-run    preview fixes
echo   [3] fix-once.py              apply fixes
echo   [q] quit
echo ==============================================
echo.
set "CHOICE="
set /p CHOICE=Select: 

if /i "%CHOICE%"=="q" goto quit
if "%CHOICE%"=="1" goto run1
if "%CHOICE%"=="2" goto run2
if "%CHOICE%"=="3" goto run3
echo.
echo [WARN] invalid choice
pause
goto menu

:run1
cls
echo [RUN] %PY% fix-once.py --check
echo ==============================================
%PY% fix-once.py --check
set "RC=%ERRORLEVEL%"
goto after

:run2
cls
echo [RUN] %PY% fix-once.py --dry-run
echo ==============================================
%PY% fix-once.py --dry-run
set "RC=%ERRORLEVEL%"
goto after

:run3
cls
echo [RUN] %PY% fix-once.py
echo ==============================================
%PY% fix-once.py
set "RC=%ERRORLEVEL%"
goto after

:after
echo.
echo ==============================================
if "%RC%"=="0" (
    echo [OK] done
) else (
    echo [ERROR] failed ^(RC=%RC%^)
)
echo ==============================================
echo.
pause >nul
goto menu

:quit
endlocal
exit /b 0