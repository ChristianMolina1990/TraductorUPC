@echo off
REM Solo para el modo de conexion "cdp" (enganchar a tu propio Chrome).
REM Abre una ventana de Chrome con depuracion remota y un perfil aparte,
REM para no interferir con tu Chrome normal. Inicia sesion en la clase en esa ventana.

set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo No se encontro chrome.exe. Edita la ruta en este .bat.
  exit /b 1
)

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\chrome-traductor"
echo Chrome abierto con depuracion en el puerto 9222.
echo En la app elige modo de conexion "Enganchar a mi Chrome (CDP :9222)".
