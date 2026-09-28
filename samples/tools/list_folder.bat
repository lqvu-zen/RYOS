@echo off
rem A batch file: runs with cmd. Lists the samples folder.
echo Files in %~dp0..
dir /b "%~dp0.."
