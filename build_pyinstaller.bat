@echo off
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
