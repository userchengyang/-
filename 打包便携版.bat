@echo off
rem ------------------------------------------------------------------
rem  IMPORTANT: keep this file ASCII-only (no Chinese characters).
rem  cmd.exe loses its read position after multi-byte chars in a .bat
rem  and chops the first bytes off every following line.
rem  All Chinese text lives in MSG.txt and is printed by :say below.
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "DEST=%USERPROFILE%\OneDrive\Desktop\AAA"
if not exist "%USERPROFILE%\OneDrive\Desktop" set "DEST=%USERPROFILE%\Desktop\AAA"

call :say pack_banner
echo   source : %~dp0
echo   target : %DEST%
echo ============================================================
echo.

if exist "%DEST%" (
    call :say pack_cleaning
    rmdir /s /q "%DEST%"
) else (
    echo [1/3] creating target dir ...
)
mkdir "%DEST%" 2>nul

call :say pack_copying

rem Copy everything except build artifacts, secrets and the .bat helpers.
rem Note the trailing dot on %~dp0. : it keeps robocopy from seeing a
rem path that ends in a backslash-quote pair, which it misparses.
robocopy "%~dp0." "%DEST%" /E /XD ".git" "__pycache__" /XF "Dockerfile" ".gitignore" "chaoxing.log" "config.ini" "cookies.txt" "cache.json" "*.bat" /NFL /NDL /NJH /NJS /NP >nul

rem Put the launcher back, under its original (Chinese) filename.
rem Found by its marker so no non-ASCII literal is needed here.
for %%f in ("%~dp0*.bat") do (
    findstr /m /c:"CX_LAUNCHER" "%%f" >nul 2>nul
    if not errorlevel 1 copy /y "%%f" "%DEST%\%%~nxf" >nul
)

rem The builder is copied under an ASCII name because this script has to
rem reference it by name, and it gets deleted from the target afterwards.
for %%f in ("%~dp0*.bat") do (
    findstr /m /c:"CX_BUILDER" "%%f" >nul 2>nul
    if not errorlevel 1 copy /y "%%f" "%DEST%\make-portable.bat" >nul
)

if not exist "%DEST%\main.py" (
    call :say pack_copy_fail
    echo.
    pause
    exit /b 1
)

echo.
call :say pack_building
echo.
call "%DEST%\make-portable.bat"

if not exist "%DEST%\python\python.exe" (
    echo.
    call :say pack_fail
    echo.
    pause
    exit /b 1
)

del /q "%DEST%\make-portable.bat" >nul 2>nul

echo.
call :say pack_done
echo.
pause
exit /b 0

rem ------------------------------------------------------------------
rem  :say <section>  -- print a block from MSG.txt (UTF-8) to console
rem ------------------------------------------------------------------
:say
powershell -NoProfile -Command "$L=@(Get-Content -LiteralPath '%~dp0MSG.txt' -Encoding UTF8); $s=[Array]::IndexOf($L,'#%~1'); if($s -lt 0){exit}; $e=$s+1; while($e -lt $L.Count -and -not $L[$e].StartsWith('#')){$e++}; for($i=$s+1;$i -lt $e;$i++){Write-Host $L[$i]}"
goto :eof
