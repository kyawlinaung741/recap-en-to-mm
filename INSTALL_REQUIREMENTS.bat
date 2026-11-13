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
call :setup_ollama
if errorlevel 1 goto :ollama_fail

echo.
echo ================================================================
echo  INSTALLATION COMPLETE
echo ================================================================
echo Python requirements, Chromium, FFmpeg, Ollama, and qwen3:4b
echo are ready.
echo.
echo Put your Gemini key in .env (copy .env.example), then run RUN.bat.
echo Ollama model: qwen3:4b
echo.
pause
exit /b 0

:setup_ollama
set "OLLAMA_EXE="
where ollama.exe >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where ollama.exe') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
)

if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"

if defined OLLAMA_EXE goto :ollama_found

echo Ollama was not found. Trying installation with Windows winget...
where winget.exe >nul 2>nul
if errorlevel 1 (
    echo winget is unavailable. Please install Ollama from https://ollama.com/download
    echo Then close and reopen this window and run INSTALL_REQUIREMENTS.bat again.
    exit /b 1
)

winget install --id Ollama.Ollama --exact --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Ollama installation through winget failed.
    echo Install it manually from https://ollama.com/download and rerun this installer.
    exit /b 1
)

rem Refresh PATH for this installer process after winget installation.
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
if not defined OLLAMA_EXE (
    for /f "delims=" %%I in ('where ollama.exe 2^>nul') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
)
if not defined OLLAMA_EXE (
    echo Ollama was installed, but ollama.exe was not found in the usual locations.
    echo Restart Windows or install Ollama manually, then rerun this installer.
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
