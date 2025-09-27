:: One file version

@echo off
setlocal enabledelayedexpansion

rem === Read version number from file ===
set /p VERSION=<"..\redvypr\VERSION"
echo Building redvypr version %VERSION%

rem === Define build and dist folders with version number ===
set BUILDDIR=build_%VERSION%
set DISTDIR=dist_%VERSION%

rem === Remove old folders if they exist ===
if exist "%BUILDDIR%" rmdir /s /q "%BUILDDIR%"
if exist "%DISTDIR%" rmdir /s /q "%DISTDIR%"

pyinstaller ^
 -i "..\redvypr\icon\icon_v03.3.ico" ^
 --add-data "../redvypr/VERSION;." ^
 --onefile ^
 --workpath "%BUILDDIR%" ^
 --distpath "%DISTDIR%" ^
 --collect-all matplotlib ^
 --collect-all serial ^
 --collect-all pynmea2 ^
 --collect-all xlsxwriter ^
 --collect-all xarray ^
 --collect-all netCDF4 ^
 --collect-all pympler ^
 --collect-all pyqtgraph ^
 --collect-all numpy ^
 --collect-all PyQt6 ^
 --collect-all redvypr ^
 --collect-all pyqtconsole ^
 --hidden-import qtawesome ^
 --hidden-import deepdiff ^
 --hidden-import pyqtconsole ^
 --hidden-import pydantic ^
 --hidden-import uuid ^
 --hidden-import yaml ^
 --hidden-import pyyaml ^
 --hidden-import pkg_resources ^
 --name redvypr_%VERSION% ^
 redvypr_run.py


echo.
echo === Build finished ===
echo Executable is located at: %DISTDIR%\redvypr_%VERSION%.exe
pause