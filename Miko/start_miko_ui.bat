@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Miko's Python environment is missing.
  echo Run setup first: python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run streamlit_app.py
pause
