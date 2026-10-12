@echo off
rem CX_LAUNCHER
rem ------------------------------------------------------------------
rem  IMPORTANT: keep this file ASCII-only (no Chinese characters).
rem  cmd.exe loses its read position after multi-byte chars in a .bat
rem  and chops the first bytes off every following line.
rem  All Chinese text lives in MSG.txt and is printed by :say below.
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

call :say banner
echo.

set "PYEXE="

rem ---- 1) bundled portable Python (no install needed) ----
if exist "python\python.exe" set "PYEXE=python\python.exe"

rem ---- 2) fall back to a system Python ----
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PYEXE=python"
    )
)
if not defined PYEXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
    )
)
if not defined PYEXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
    )
)
if not defined PYEXE (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
    )
)
if not defined PYEXE (
    for /d %%D in ("C:\Python3*") do (
        if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
    )
)

if not defined PYEXE (
    call :say no_python
    echo.
    pause
    exit /b 1
)

echo   Python: %PYEXE%
echo.

rem ---- version check ----
"%PYEXE%" -c "import sys;sys.exit(0 if sys.version_info[0]>=3 and sys.version_info[1]>=13 else 1)" >nul 2>nul
if errorlevel 1 (
    "%PYEXE%" --version
    call :say old_python
    echo.
    pause
    exit /b 1
)

rem ---- dependency check (bundled python has them in vendor\) ----
"%PYEXE%" -c "import requests, loguru, openai, tqdm, bs4, lxml, pyaes, fontTools, httpx, chardet, tenacity, urllib3" >nul 2>nul
if errorlevel 1 (
    echo [i] Installing dependencies, please wait ...
    "%PYEXE%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 "%PYEXE%" -m pip install -r requirements.txt
    "%PYEXE%" -c "import requests, loguru, openai, tqdm, bs4, lxml, pyaes, fontTools, httpx, chardet, tenacity, urllib3" >nul 2>nul
    if errorlevel 1 (
        call :say deps_fail
        echo.
        pause
        exit /b 1
    )
)

"%PYEXE%" main.py %*

echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem  :say <section>  -- print a block from MSG.txt (UTF-8) to console
rem ------------------------------------------------------------------
:say
powershell -NoProfile -Command "$L=@(Get-Content -LiteralPath '%~dp0MSG.txt' -Encoding UTF8); $s=[Array]::IndexOf($L,'#%~1'); if($s -lt 0){exit}; $e=$s+1; while($e -lt $L.Count -and -not $L[$e].StartsWith('#')){$e++}; for($i=$s+1;$i -lt $e;$i++){Write-Host $L[$i]}"
goto :eof
