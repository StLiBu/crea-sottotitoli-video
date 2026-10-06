@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Primo avvio: preparo l'ambiente Python e installo i componenti.
  where py >nul 2>nul
  if errorlevel 1 (
    echo ERRORE: non trovo il launcher Python. Installa Python 3.10 o successivo da python.org.
    pause
    exit /b 1
  )
  py -3 -m venv "%ROOT%.venv"
  if errorlevel 1 goto install_error
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%prepare_certificates.py"
  if errorlevel 1 goto install_error
  set "PIP_CERT=%ROOT%_cache\windows-ca-bundle.pem"
  "%ROOT%\.venv\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt"
  if errorlevel 1 goto install_error
)
set "VIDEO_SUBS_ROOT=%ROOT%"
set "VIDEO_SUBS_MODEL_DIR=%ROOT%models"
set "HF_HOME=%ROOT%_cache\hf_home"
set "HUGGINGFACE_HUB_CACHE=%ROOT%_cache\hf_home\hub"
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%video_subtitles.py" %*
if errorlevel 1 pause
exit /b
:install_error
echo.
echo ERRORE durante la preparazione. Controlla Python e la connessione Internet, poi riprova.
pause
exit /b 1
