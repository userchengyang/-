@echo off
rem CX_BUILDER
rem ------------------------------------------------------------------
rem  IMPORTANT: keep this file ASCII-only (no Chinese characters).
rem  cmd.exe loses its read position after multi-byte chars in a .bat
rem  and chops the first bytes off every following line.
rem  All Chinese text lives in MSG.txt and is printed by :say below.
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

call :say build_banner
echo.

rem ---- locate a system Python ----
set "SYS="
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "SYS=python"
)
if not defined SYS (
    where py >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "SYS=%%P"
    )
)
if not defined SYS (
    call :say build_no_python
    echo.
    pause
    exit /b 1
)

rem A quoted exe path inside for /f gets mangled by cmd /c, so have the
rem interpreter write its version into a temp file and read that back.
set "PYINFO=%TEMP%\cx_pyinfo_%RANDOM%.txt"
"%SYS%" -c "import sys,struct;open(r'%PYINFO%','w').write('.'.join(map(str,sys.version_info[:3]))+','+'{}{}'.format(*sys.version_info[:2])+','+('win32' if struct.calcsize('P')==4 else 'amd64'))"
if errorlevel 1 (
    echo [ERROR] cannot run: %SYS%
    pause
    exit /b 1
)
if not exist "%PYINFO%" (
    echo [ERROR] cannot read python version info
    pause
    exit /b 1
)
for /f "usebackq tokens=1,2,3 delims=," %%a in ("%PYINFO%") do (
    set "PYVER=%%a"
    set "PYTAG=%%b"
    set "PYARCH=%%c"
)
del /q "%PYINFO%" >nul 2>nul

if not defined PYVER (
    echo [ERROR] cannot detect python version
    pause
    exit /b 1
)

echo   Build Python : %SYS%
echo   Version      : %PYVER%  %PYARCH%
echo.

"%SYS%" -c "import sys;sys.exit(0 if sys.version_info[0]>=3 and sys.version_info[1]>=13 else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.13+ required, found %PYVER%
    pause
    exit /b 1
)

set "EMBED=python-%PYVER%-embed-%PYARCH%.zip"
set "URL=https://www.python.org/ftp/python/%PYVER%/%EMBED%"
set "URL2=https://mirrors.huaweicloud.com/python/%PYVER%/%EMBED%"
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

rem ---------- 1/4 download embeddable interpreter ----------
if exist "%EMBED%" (
    echo [1/4] %EMBED% already present, skipping download
    goto :have_zip
)

echo [1/4] Downloading portable Python runtime ...
echo       %URL%
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; try { Invoke-WebRequest -Uri '%URL%' -OutFile '%EMBED%' -UseBasicParsing } catch { exit 1 }"
if not errorlevel 1 goto :have_zip

echo       official mirror failed, retrying on huaweicloud ...
echo       %URL2%
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; try { Invoke-WebRequest -Uri '%URL2%' -OutFile '%EMBED%' -UseBasicParsing } catch { exit 1 }"
if not errorlevel 1 goto :have_zip

echo.
call :say build_dl_fail
echo       %URL%
echo       save as: %CD%\%EMBED%
echo.
pause
exit /b 1

:have_zip

rem ---------- 2/4 extract ----------
echo [2/4] Extracting to python\ ...
if exist "python" rmdir /s /q "python"
mkdir "python"
powershell -NoProfile -Command "Expand-Archive -Path '%EMBED%' -DestinationPath 'python' -Force"
if errorlevel 1 (
    echo [ERROR] extraction failed, delete %EMBED% and run this script again
    pause
    exit /b 1
)

rem ---------- 3/4 point the portable interpreter at vendor\ ----------
echo [3/4] Configuring sys.path ...
set "PTH=python\python%PYTAG%._pth"
if not exist "%PTH%" (
    echo [ERROR] %PTH% not found, extraction incomplete
    pause
    exit /b 1
)
(
echo python%PYTAG%.zip
echo .
echo ..\vendor
echo import site
) > "%PTH%"

rem ---------- 4/4 install dependencies ----------
echo [4/4] Installing dependencies into vendor\ ...
echo       first run downloads 100-300 MB, please be patient
echo.
if exist "vendor" rmdir /s /q "vendor"

findstr /v /i "ddddocr" requirements.txt > requirements-tmp.txt
set "PIPDST=--target vendor --upgrade --no-warn-script-location"

echo       attempt 1/3: tsinghua mirror ...
"%SYS%" -m pip install -r requirements-tmp.txt %PIPDST% --only-binary=:all: -i %MIRROR%
if not errorlevel 1 goto :deps_ok

echo.
echo       attempt 2/3: tsinghua mirror, sources allowed ...
"%SYS%" -m pip install -r requirements-tmp.txt %PIPDST% -i %MIRROR%
if not errorlevel 1 goto :deps_ok

echo.
echo       attempt 3/3: official PyPI ...
"%SYS%" -m pip install -r requirements-tmp.txt %PIPDST%
if not errorlevel 1 goto :deps_ok

del /q requirements-tmp.txt >nul 2>nul
echo.
call :say build_deps_fail
echo.
pause
exit /b 1

:deps_ok
del /q requirements-tmp.txt >nul 2>nul

rem ddddocr is optional (the program does not use captcha solving yet)
echo.
echo       installing optional ddddocr ...
"%SYS%" -m pip install ddddocr --target vendor --upgrade --no-warn-script-location -i %MIRROR%
if errorlevel 1 echo       [WARN] ddddocr skipped, the program still works

rem ---------- self test ----------
echo.
echo Self test ...
"python\python.exe" -c "import requests, loguru, openai, tqdm, bs4, lxml, pyaes, fontTools, httpx, chardet, tenacity, urllib3; print('  core deps OK')"
if errorlevel 1 (
    echo.
    echo [ERROR] portable runtime self test failed - see the error above
    echo.
    pause
    exit /b 1
)
"python\python.exe" -c "import ddddocr; print('  ddddocr OK')" 2>nul
if errorlevel 1 echo   [i] ddddocr not available (optional, no impact)

del /q "%EMBED%" >nul 2>nul

echo.
call :say build_done
echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem  :say <section>  -- print a block from MSG.txt (UTF-8) to console
rem ------------------------------------------------------------------
:say
powershell -NoProfile -Command "$L=@(Get-Content -LiteralPath '%~dp0MSG.txt' -Encoding UTF8); $s=[Array]::IndexOf($L,'#%~1'); if($s -lt 0){exit}; $e=$s+1; while($e -lt $L.Count -and -not $L[$e].StartsWith('#')){$e++}; for($i=$s+1;$i -lt $e;$i++){Write-Host $L[$i]}"
goto :eof
