@echo off
REM === EXPERIMENTAL / unsupported. Single-file build with extra AV flags.
REM === The supported build is build.bat (cx_Freeze). Use this only if you
REM === specifically need a Nuitka one-file exe.
cd /d "%~dp0"
uv run --with nuitka --with tkinterdnd2 python -m nuitka ^
  --onefile ^
  --python-flag=-m ^
  --assume-yes-for-downloads ^
  --msvc=latest ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=icon.ico ^
  --enable-plugin=tk-inter ^
  --include-package=tkinterdnd2 ^
  --include-package-data=tkinterdnd2 ^
  --include-data-files=icon.ico=icon.ico ^
  --output-filename=RYOS.exe ^
  --output-dir=dist ^
  --remove-output ^
  ryos
echo.
if exist dist\RYOS.exe (echo Build successful: dist\RYOS.exe) else (echo Build failed.)
pause
