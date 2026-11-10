@echo off
set OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe

if not exist "%OLLAMA_EXE%" (
  echo Ollama was not found at "%OLLAMA_EXE%".
  echo Open Ollama first or reinstall it from https://ollama.com/download
  pause
  exit /b 1
)

"%OLLAMA_EXE%" pull llama3.1:8b
pause
