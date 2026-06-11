@echo off
REM === EXPERIMENTAL / unsupported. Single-file PyInstaller build.
REM === The supported build is build.bat (cx_Freeze). Use this only if you
REM === specifically need a PyInstaller one-file exe.
cd /d "%~dp0"
uv run --with pyinstaller --with tkinterdnd2 pyinstaller ^
  --onefile ^
  --windowed ^
  --icon="%~dp0icon.ico" ^
  --name=RYOS ^
  --collect-all tkinterdnd2 ^
  --add-data "%~dp0icon.ico;." ^
  --distpath dist ^
  --workpath build\pyinstaller ^
  --specpath build\pyinstaller ^
  --noconfirm ^
  _packed_entry.py
echo.
if exist dist\RYOS.exe (echo Build successful: dist\RYOS.exe) else (echo Build failed.)
pause
