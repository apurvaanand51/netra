@echo off
REM NETRA -- one-command start (Windows).
REM
REM   run.bat              prepare if needed, then serve
REM   run.bat --fresh      regenerate the dataset and retrain first
REM   run.bat --port 9000  serve on a different port
REM
REM Same sequence as run.sh. The team practises on Windows and ships on Linux,
REM so both scripts exist and both call the same tasks.py -- there is one
REM implementation of the pipeline, and these only handle the shell differences.
setlocal enabledelayedexpansion

cd /d "%~dp0"

set PORT=8000
set FRESH=0

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--fresh" ( set FRESH=1 & shift & goto parse )
if /i "%~1"=="--port"  ( set PORT=%~2 & shift & shift & goto parse )
if /i "%~1"=="-h"      goto usage
if /i "%~1"=="--help"  goto usage
echo unknown option: %~1
exit /b 2

:usage
echo   run.bat              prepare if needed, then serve
echo   run.bat --fresh      regenerate the dataset and retrain first
echo   run.bat --port 9000  serve on a different port
exit /b 0

:parsed

REM ---- 1. Python ---------------------------------------------------------
REM 3.10 specifically: that is the version the pipeline was verified against.
py -3.10 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.10 not found. Install it, or make sure the "py" launcher
  echo        can find it:  py -0p
  exit /b 1
)

REM ---- 2. Environment ----------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo ==^> creating virtual environment
  py -3.10 -m venv .venv
)
set PYTHON=.venv\Scripts\python.exe

%PYTHON% -c "import fastapi, sklearn, pandas, networkx, jsonschema" >nul 2>&1
if errorlevel 1 (
  echo ==^> installing dependencies
  if exist "wheels" (
    echo     ^(offline: using the vendored wheels\^)
    %PYTHON% -m pip install --no-index --find-links=wheels/ -r requirements.txt
  ) else (
    %PYTHON% -m pip install -r requirements.txt
  )
)

REM ---- 3. Data, models, history ------------------------------------------
if "%FRESH%"=="1" goto rebuild
if not exist "models\risk.joblib" goto rebuild
if not exist "data\transactions.csv" goto rebuild
goto afterbuild

:rebuild
echo ==^> generating the dataset
%PYTHON% tasks.py gen
if errorlevel 1 exit /b 1
echo ==^> training and measuring the models
%PYTHON% tasks.py train
if errorlevel 1 exit /b 1

:afterbuild
if "%FRESH%"=="1" goto replay
if not exist "out\monitoring.sqlite" goto replay
goto serve

:replay
echo ==^> running the windowed pipeline
%PYTHON% tasks.py replay
if errorlevel 1 exit /b 1

:serve
echo.
echo   NETRA is starting on http://localhost:%PORT%
echo     Ingest      http://localhost:%PORT%/
echo     Traffic     http://localhost:%PORT%/traffic.html
echo     Investigate http://localhost:%PORT%/investigate.html
echo     Monitoring  http://localhost:%PORT%/monitoring.html
echo     Method      http://localhost:%PORT%/model.html
echo     Documents   http://localhost:%PORT%/documents.html
echo     API console http://localhost:%PORT%/docs
echo.
echo   Offline check: unplug the network now. Everything above keeps working.
echo.

%PYTHON% -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
endlocal
