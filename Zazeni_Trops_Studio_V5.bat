@echo off
rem Trops Studio 5.1.00 - zagon (Python 3.10+, Edge WebView2), brez konzolnega okna (pyw)
cd /d "%~dp0"
where pyw >nul 2>&1
if %errorlevel%==0 (
  py -3.10 -c "" >nul 2>&1
  if not errorlevel 1 (
    start "" pyw -3.10 "%~dp0Trops_Studio_V5.1.00.pyw" %*
    exit /b 0
  )
  start "" pyw -3 "%~dp0Trops_Studio_V5.1.00.pyw" %*
  exit /b 0
)
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw "%~dp0Trops_Studio_V5.1.00.pyw" %*
) else (
  start "" python "%~dp0Trops_Studio_V5.1.00.pyw" %*
)
exit /b 0
