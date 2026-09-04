@echo off
REM Instalacion unica. Necesita internet SOLO en este paso.
setlocal

echo === 1/4  Instalando dependencias de Python ===
py -m pip install --upgrade pip
py -m pip install -r requirements.txt || goto :err

echo.
echo === 2/4  Descargando el navegador de Playwright (Chromium, ~150 MB) ===
py -m playwright install chromium || goto :err

echo.
echo === 3/4  Descargando modelo de idioma offline  ingles -^> espanol ===
py scripts\install_lang.py en es || echo   (puedes instalarlo luego desde la interfaz)

echo.
echo === 4/4  Listo ===
echo Ejecuta:   py run.py
echo Luego abre http://127.0.0.1:8000/ (se abre solo)
goto :eof

:err
echo.
echo *** Fallo la instalacion. Revisa el error de arriba. ***
exit /b 1
