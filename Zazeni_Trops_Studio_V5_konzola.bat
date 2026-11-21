@echo off
rem Trops Studio 5.1.00 - zagon S KONZOLO (za iskanje napak; izpisi Pythona ostanejo vidni)
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3.10 "%~dp0Trops_Studio_V5.1.00.pyw" %*
) else (
  python "%~dp0Trops_Studio_V5.1.00.pyw" %*
)
echo.
echo Program je koncal (izhodna koda %errorlevel%).
pause
