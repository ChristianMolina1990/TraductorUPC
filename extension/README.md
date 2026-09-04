# Extensión: puente de transcripción

Lee el panel de subtítulos de **la pestaña que ya tienes abierta** (con tu
sesión, sin reiniciar Chrome) y envía el texto al Traductor local
(`http://localhost:8000/api/ingest`). El backend traduce sin conexión.

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

## Notas

- Detecta el panel automáticamente (elementos tipo *caption / transcript /
  subtitle / aria-live*). Si acierta con otro elemento, escribe un selector CSS
  en el campo **Selector** de la app: la extensión lo lee cada pocos segundos.
- Funciona en cualquier sitio (Zoom web, Meet, Teams, class.com…), no solo la UPC.
- No envía nada fuera de tu equipo: solo hace POST a `localhost:8000`.
- Si recargas la extensión en `chrome://extensions`, recarga también la pestaña
  de la clase.
