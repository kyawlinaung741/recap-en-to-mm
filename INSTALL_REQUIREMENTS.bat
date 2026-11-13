@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Install Recap English to Myanmar requirements

set "PY=python"
where py >nul 2>nul && set "PY=py -3.12"

echo.
echo ================================================================
echo  Recap English to Myanmar - Requirements Installer
echo ================================================================
echo.

echo [1/5] Updating pip...
%PY% -m pip install --upgrade pip || goto :fail

echo.
echo [2/5] Installing Python packages from requirements.txt...
%PY% -m pip install -r requirements.txt || goto :fail

echo.
echo [3/5] Installing Chromium for the Myanmar text renderer...
%PY% -m playwright install chromium || goto :fail

echo.
echo [4/5] Checking FFmpeg...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\get_ffmpeg.ps1"
if errorlevel 1 goto :ffmpeg_fail

echo.
echo [5/5] Installing Ollama and downloading Qwen3:4b...
set "OLLAMA_EXE="
where ollama.exe >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where ollama.exe') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
)

if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"

if defined OLLAMA_EXE goto :ollama_found

echo Ollama was not found. Installing automatically from the official Ollama installer...
echo This may download a large Windows package. Please wait; no manual setup is needed.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { irm https://ollama.com/install.ps1 | iex; exit 0 } catch { Write-Error $_; exit 1 }"
if errorlevel 1 (
    echo Official Ollama installation failed.
    exit /b 1
)

rem The official installer updates the current PowerShell PATH only.
rem Resolve the executable directly for this batch process.
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
if not defined OLLAMA_EXE (
    for /f "delims=" %%I in ('where ollama.exe 2^>nul') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
)
if not defined OLLAMA_EXE (
    echo Ollama installer finished, but ollama.exe could not be located.
    exit /b 1
)

:ollama_found
echo Ollama executable: "%OLLAMA_EXE%"

rem Start the local Ollama server only when it is not already responding.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:11434/api/tags; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo Starting Ollama local service...
    start "Ollama Server" /min "%OLLAMA_EXE%" serve
)

echo Waiting for Ollama service...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ready=$false; for($i=0; $i -lt 45; $i++){ try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:11434/api/tags ^| Out-Null; $ready=$true; break } catch { Start-Sleep -Seconds 2 } }; if(-not $ready){ Write-Error 'Ollama service did not become ready on 127.0.0.1:11434'; exit 1 }"
if errorlevel 1 exit /b 1

echo Downloading Qwen3:4b. This download is several GB and may take time...
"%OLLAMA_EXE%" pull qwen3:4b
if errorlevel 1 exit /b 1

echo Verifying qwen3:4b...
"%OLLAMA_EXE%" show qwen3:4b >nul 2>nul
if errorlevel 1 exit /b 1
exit /b 0

:ffmpeg_fail
echo.
echo FFmpeg could not be downloaded automatically.
echo Download it from https://www.gyan.dev/ffmpeg/builds/ (ffmpeg-release-essentials.zip)
echo and copy ffmpeg.exe and ffprobe.exe from its bin folder into the "ffmpeg" folder next to RUN.bat.
pause
exit /b 1

:ollama_fail
echo.
echo Ollama or qwen3:4b setup failed.
echo Check your internet connection and available disk space, then rerun this installer.
echo You can also install Ollama manually from https://ollama.com/download
pause
exit /b 1

:fail
echo.
echo FAILED - check the messages above. Python 3.12 (64-bit) and internet are needed.
pause
exit /b 1
