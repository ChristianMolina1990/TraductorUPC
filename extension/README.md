# Extensión: puente de transcripción y audio

Lee el panel de subtítulos de **la pestaña que ya tienes abierta** (con tu
sesión, sin reiniciar Chrome) y envía el texto al Traductor local
(`http://localhost:8000/api/ingest`). El backend traduce sin conexión.

También permite, desde la pestaña **Audio** de la app, elegir una pestaña
abierta y capturar su audio (`chrome.tabCapture`) para transcribirlo y
traducirlo en vivo (ver más abajo).

## Instalar (una vez)

1. Abre `chrome://extensions`.
2. Activa **Modo de desarrollador** (arriba a la derecha).
3. **Cargar descomprimida** → selecciona esta carpeta `extension/`.
4. Debe aparecer *“Traductor — puente de transcripción”*.

## Usar

1. Arranca el backend: `py run.py`.
2. En la app (`http://localhost:8000`), modo de conexión = **Extensión de Chrome**.
3. Abre o **recarga** la pestaña de tu clase, con los subtítulos activados.
4. En la app, en el recuadro de estado, debe decir **✓ señal recibida**.
5. Pulsa **▶ Iniciar**.

## Modo Audio

Chrome solo deja capturar el audio de una pestaña si el usuario hace un clic
real **sobre esa pestaña** en el icono de la extensión (por seguridad: así
ninguna web puede grabar audio de otra pestaña sin que tú lo veas). Por eso
no se elige la pestaña desde la app — se activa desde Chrome:

1. Arranca el backend: `py run.py`. Ábrelo en tu navegador `http://localhost:8000`.
2. En la app, entra a **Traductor → Audio**.
3. Si tienes varias pestañas abiertas, pulsa **↻ Listar pestañas** y usa
   **"Ir a esta pestaña"** junto a la que quieres traducir: Chrome cambia el
   foco a esa pestaña por ti.
4. Ya en esa pestaña, haz clic en el icono de la extensión **Traductor** en
   la barra de Chrome. La primera vez, Chrome puede pedir confirmar la
   captura de audio.
5. El icono muestra un punto rojo mientras captura. El texto reconocido
   aparece en la app, columna izquierda, y su traducción a la derecha, cada
   pocos segundos. Seguirás oyendo el audio con normalidad.
6. Para parar: vuelve a hacer clic en el icono (en esa misma pestaña) o pulsa
   **■ Detener** en la app.
7. La primera vez que se usa, el backend descarga el modelo de voz (Whisper)
   — offline después de eso, igual que los modelos de idioma.

## Notas

- Detecta el panel automáticamente (elementos tipo *caption / transcript /
  subtitle / aria-live*). Si acierta con otro elemento, escribe un selector CSS
  en el campo **Selector** de la app: la extensión lo lee cada pocos segundos.
- Funciona en cualquier sitio (Zoom web, Meet, Teams, class.com…), no solo la UPC.
- No envía nada fuera de tu equipo: solo hace POST a `localhost:8000`.
- Si recargas la extensión en `chrome://extensions`, recarga también la pestaña
  de la clase (y la pestaña de la app) para que vuelva a inyectarse el puente.
- La extensión no pide acceso a "todos los sitios": usa el permiso `activeTab`,
  que solo se activa para la pestaña donde haces clic en su icono, cuando lo
  haces. Es la forma que exige Chrome para `chrome.tabCapture`.
