@echo off
cd /d "%~dp0"
uv run --with pyinstaller pyinstaller RYOS.spec --noconfirm
echo.
if exist dist\RYOS.exe (
    echo Build successful: dist\RYOS.exe
) else (
    echo Build failed.
)
pause
