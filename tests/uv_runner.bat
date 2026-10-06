@echo off
rem --no-project: run the script alone. Inside the repo, plain "uv run" first
rem syncs the whole RYOS environment (PySide6), which timed out on a fresh CI runner.
uv run --no-project uv_hello.py %*
