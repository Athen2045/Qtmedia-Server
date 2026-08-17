@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

pushd "%ROOT%"

if not exist "%PYTHON%" (
    echo THEIA virtual environment not found at "%ROOT%.venv".
    echo Create it once with: py -3.11 -m venv .venv
    echo Then install dependencies with: .venv\Scripts\python.exe -m pip install -e ".[dev]"
    popd
    endlocal
    exit /b 1
)

"%PYTHON%" "%ROOT%main.py"
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
1
