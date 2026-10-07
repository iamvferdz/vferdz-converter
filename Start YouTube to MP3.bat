@echo off
setlocal
pushd "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer and try again.
    goto :failed
)

python -c "import yt_dlp" >nul 2>nul
if errorlevel 1 (
    echo The app dependency is missing. Install it with:
    echo   python -m pip install -r requirements.txt
    goto :failed
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo FFmpeg was not found. Install FFmpeg and make sure it is on PATH.
    goto :failed
)

python local_web_app.py
set "app_exit_code=%errorlevel%"
popd
if not "%app_exit_code%"=="0" (
    echo The app exited with code %app_exit_code%.
    pause
)
exit /b %app_exit_code%

:failed
popd
echo.
pause
exit /b 1
