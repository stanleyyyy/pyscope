@echo off
rem ===========================================================================
rem build_installer.bat  -  build the shareable Setup exe with Inno Setup
rem   1. ensures the bundle exists (dist\pyscope\pyscope.exe), building if not
rem   2. compiles installer\pyscope.iss -> installer\Output\pyscope-Setup.exe
rem Requires Inno Setup (iscc) on PATH:  scoop install inno-setup
rem ===========================================================================
setlocal
cd /d "%~dp0"
title pyscope - build installer

if not exist "..\dist\pyscope\pyscope.exe" (
    echo dist\pyscope\pyscope.exe not found -- building the app first...
    call "..\build.bat" --no-pause || exit /b 1
)

where iscc >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] Inno Setup compiler ^(iscc^) not found.
    echo     Install it with:  scoop install inno-setup
    echo     or from https://jrsoftware.org/isdl.php
    echo.
    pause
    exit /b 1
)

rem Version comes from pyproject.toml so the installer never disagrees with pip.
set PY=python
where py >nul 2>&1 && set PY=py
for /f "delims=" %%v in ('%PY% -c "import tomllib;print(tomllib.load(open('../pyproject.toml','rb'))['project']['version'])"') do set VERSION=%%v
if "%VERSION%"=="" set VERSION=0.0.0

echo Compiling installer for version %VERSION%...
iscc /DAppVersion=%VERSION% "pyscope.iss" || goto :err

echo.
echo ---------------------------------------------------------------------------
echo Installer built: %~dp0Output\pyscope-Setup.exe
echo Share that single file. Recipients just run it -- no Python needed.
echo ---------------------------------------------------------------------------
if /i not "%1"=="--no-pause" pause
exit /b 0

:err
echo.
echo [!] Installer build failed. See messages above.
if /i not "%1"=="--no-pause" pause
exit /b 1
