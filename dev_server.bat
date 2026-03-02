@echo off
title MJ Port — Dev Server + ngrok
echo Starting FastAPI server and ngrok tunnel...
echo.

:: Python path
set PYTHON=C:\Users\mkamo\AppData\Local\Programs\Python\Python314\python.exe
set NGROK=C:\Users\mkamo\AppData\Local\ngrok\ngrok.exe

:: Start uvicorn in a new window
start "MJ Port Server" cmd /k "%PYTHON% -m uvicorn server.main:app --host 0.0.0.0 --port 8000"

:: Wait for server to start
timeout /t 3 /nobreak >nul

:: Start ngrok in a new window
start "ngrok" cmd /k "%NGROK% http 8000 --url=axiomatic-aryana-hillocky.ngrok-free.dev"

echo.
echo Server:  http://localhost:8000
echo Tunnel:  https://axiomatic-aryana-hillocky.ngrok-free.dev
echo Health:  https://axiomatic-aryana-hillocky.ngrok-free.dev/health
echo.
echo Close the opened windows to stop.
