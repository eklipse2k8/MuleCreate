@echo off
rem Start Mule from the source code on Windows.
rem First start: creates its own Python environment .venv in this folder (needs Python 3.14 from python.org and
rem internet once, a few minutes). Later starts: no internet. Missing packages are installed again automatically.
rem Without Python: use Mule_Windows.zip from the releases instead (no installation needed).
setlocal
cd /d "%~dp0"
set "VPY=.venv\Scripts\python.exe"

if not exist "%VPY%" (
    echo First start: setting up Mule's own Python environment in .venv ...
    where py >nul 2>nul || goto nopython
    py -3.14 -c "import sys" >nul 2>nul || goto nopython
    py -3.14 -m venv .venv || goto failed
)
"%VPY%" -c "import PySide6, numpy, moderngl, scipy, pxr" >nul 2>nul && goto run
echo Installing the packages from requirements.txt (internet needed, a few minutes) ...
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt || goto failed

:run
if defined MULE_SETUP_ONLY exit /b 0
start "" ".venv\Scripts\pythonw.exe" -m sketch_machine
exit /b 0

:nopython
echo.
echo Python 3.14 was not found.
echo  - Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then start again,
echo  - or download Mule_Windows.zip from the releases: it runs without Python.
pause
exit /b 1

:failed
echo.
echo Setting up failed (see above). Delete the folder .venv and start again; internet is needed once.
echo If the error mentions long paths: move this folder to a short path such as C:\Mule and start again.
pause
exit /b 1
