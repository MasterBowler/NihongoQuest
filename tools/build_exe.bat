@echo off
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo Create the venv first:  py -3.14 -m venv .venv ^& .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)
if not exist "data\content.db" (
  echo Missing data\content.db — run tools\fetch_sources.py and tools\build_data.py first.
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -U pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean NihongoQuest.spec
if errorlevel 1 exit /b 1
rem Intermediate bootloader under build\ looks like an app but has no _internal\ — remove it
if exist "build\NihongoQuest\NihongoQuest.exe" del /q "build\NihongoQuest\NihongoQuest.exe"
echo.
echo Run this (not anything under build\):
echo   dist\NihongoQuest\NihongoQuest.exe
echo Zip the whole dist\NihongoQuest folder for a GitHub Release.
echo Note: Immersion Manga OCR (torch/manga-ocr) is not bundled — use run.bat for that.
