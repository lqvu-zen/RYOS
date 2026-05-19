@echo off
cd /d "%~dp0"
uv run --with pyinstaller pyinstaller ScriptRunner.spec --noconfirm
echo.
if exist dist\ScriptRunner.exe (
    echo Build successful: dist\ScriptRunner.exe
) else (
    echo Build failed.
)
pause
