@echo off
REM === Canonical, supported build (folder under dist/cxfreeze). Invoked by build.bat.
cd /d "%~dp0"
uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe
echo.
if exist dist\cxfreeze\RYOS.exe (echo Build successful: dist\cxfreeze\RYOS.exe) else (echo Build failed.)
pause
