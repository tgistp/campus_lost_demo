@echo off
setlocal
if not exist "%~dp0app.py" (
  echo ERROR: app.py was not found next to run.cmd.
  echo Extract the entire ZIP, open the campus-lost folder, then run run.cmd.
  echo Do not move run.cmd out of the extracted folder.
  pause
  exit /b 1
)
pushd "%~dp0"
if errorlevel 1 (
  echo ERROR: Cannot open the application folder.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  set "CAMPUS_PYTHON=%CD%\.venv\Scripts\python.exe"
) else if exist "%USERPROFILE%\.venv\Scripts\python.exe" (
  set "CAMPUS_PYTHON=%USERPROFILE%\.venv\Scripts\python.exe"
) else (
  set "CAMPUS_PYTHON=python"
)
echo Preparing demo items...
"%CAMPUS_PYTHON%" "%~dp0seed_demo.py"
if errorlevel 1 (
  echo ERROR: Setup failed. Install the requirements as described in the readme.
  popd
  pause
  exit /b 1
)
"%CAMPUS_PYTHON%" -m streamlit run "%~dp0app.py"
popd
pause
