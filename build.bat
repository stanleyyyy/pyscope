@echo off
rem ===========================================================================
rem build.bat  -  build the standalone pyscope bundle with PyInstaller
rem Output: dist\pyscope\  (pyscope.exe + pyscope-cli.exe + libraries)
rem         No Python needed on target machines.
rem ===========================================================================
setlocal
cd /d "%~dp0"
title pyscope - build

set PY=python
where py >nul 2>&1 && set PY=py

echo Installing build/runtime deps...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install --upgrade . pyinstaller || goto :err

echo.
echo Building bundle (this takes a minute or two)...
%PY% -m PyInstaller --noconfirm --clean pyscope.spec || goto :err

echo.
echo ---------------------------------------------------------------------------
echo Built: %~dp0dist\pyscope\pyscope.exe      (GUI)
echo        %~dp0dist\pyscope\pyscope-cli.exe  (console, for --list-devices)
echo Next:  installer\build_installer.bat  to wrap it in a Setup exe
echo ---------------------------------------------------------------------------
if /i not "%1"=="--no-pause" pause
exit /b 0

:err
echo.
echo [!] Build failed. See the messages above.
if /i not "%1"=="--no-pause" pause
exit /b 1
