@echo off
setlocal
title Daniel Local Operations Assistant Installer

set "REPO=%~dp0"
set "VENV_PYTHON=%REPO%.venv\Scripts\python.exe"
set "DATA_DIR=%USERPROFILE%\.local-operations-assistant"

echo.
echo Installing Daniel Local Operations Assistant...
echo Repository: %REPO%
echo.

where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python launcher was not found.
  echo Install Python 3.11 or newer, then run this installer again.
  goto :fail
)

where ollama >nul 2>&1
if errorlevel 1 (
  echo ERROR: Ollama was not found.
  echo Install Ollama, then run this installer again.
  goto :fail
)

where codex >nul 2>&1
if errorlevel 1 (
  echo ERROR: Codex CLI was not found.
  echo Install or enable Codex CLI, then run this installer again.
  goto :fail
)

if not exist "%VENV_PYTHON%" (
  echo Creating private Python environment...
  py -m venv "%REPO%.venv"
  if errorlevel 1 goto :fail
)

echo Installing required packages...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%REPO%requirements.txt"
if errorlevel 1 goto :fail

echo Installing local embedding model...
ollama pull embeddinggemma
if errorlevel 1 goto :fail

echo Registering MCP server with Codex...
codex mcp remove local-operations-assistant >nul 2>&1
codex mcp add local-operations-assistant --env "LOCAL_ASSISTANT_DATA_DIR=%DATA_DIR%" --env "PYTHONPATH=%REPO%" -- "%VENV_PYTHON%" -m local_assistant.server
if errorlevel 1 goto :fail

echo.
echo Verifying registration...
codex mcp list
if errorlevel 1 goto :fail

echo.
echo SUCCESS: Local Operations Assistant is installed and registered.
echo Completely restart ChatGPT or Codex, then open a new session.
echo.
pause
exit /b 0

:fail
echo.
echo INSTALLATION FAILED. Leave this window open and send a picture of the error.
echo.
pause
exit /b 1
