@echo off
echo Installing uv...
powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
echo.
echo Done. Restart your terminal for uv to be available in PATH.
pause
