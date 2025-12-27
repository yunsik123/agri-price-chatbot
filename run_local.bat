@echo off
echo ============================================
echo   Agricultural Price Chatbot - Local Server
echo ============================================
echo.

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Install dependencies if needed
echo Checking dependencies...
pip install -q fastapi uvicorn

REM Run the server
echo.
echo Starting local server...
echo.
echo Access the chatbot at:
echo   http://localhost:8000
echo.
echo API endpoint:
echo   http://localhost:8000/api/query
echo.
echo Press Ctrl+C to stop the server
echo.

python local_server.py
