# Traductor de transcripciones en vivo

Aplicación web **local** (front + back en Python) que lee en tiempo real el panel
de transcripción de una clase/reunión abierta en el navegador y lo muestra en dos
columnas dentro de la misma ventana:

```
┌───────────────────────────┬───────────────────────────┐
│  Transcripción (original) │  Traducción (es)          │
│  ...texto en vivo...      │  ...traducción en vivo... │
└───────────────────────────┴───────────────────────────┘
```

- **100% offline** una vez instalado (traducción con Argos Translate / CTranslate2).
- Eliges la **URL** o la **pestaña** que quieres traducir.
- Selector del panel de subtítulos **automático**, con opción de elegirlo con un
  clic en la página o escribir un CSS a mano.

## Requisitos

- Windows + Python 3.11 (probado con `py` launcher).
- Internet **solo** para la instalación inicial.

## Instalación (una vez, con internet)

```bat
setup.bat
```

Esto instala dependencias, descarga el Chromium de Playwright (~150 MB) y el
modelo **inglés → español**. Para otros pares: `py scripts\install_lang.py xx yy`
o desde la interfaz (**Idiomas…**).

## Uso

```bat
py run.py
```

Se abre `http://127.0.0.1:8000/`. Luego:

1. **⚙ Configuración** → pega la **URL de la clase** y pulsa **Abrir**.
   Se abre un Chromium propio; inicia sesión en la clase ahí (solo la 1ª vez,
   el perfil queda guardado en `.chrome-profile/`).
2. Activa la transcripción/subtítulos en la clase.
3. (Opcional) **Elegir en la página** → clic sobre el panel de subtítulos para
   fijar el selector. O deja el selector vacío para detección automática.
   Usa **Probar** para ver qué está leyendo.
4. Elige **idioma origen → destino**.
5. **▶ Iniciar**. El texto va apareciendo y traduciéndose frase a frase.

### Modo recomendado: extensión de Chrome (pestaña que ya tienes abierta)

Para leer **tu pestaña actual, con tu sesión y sin reiniciar nada**:

1. `chrome://extensions` → **Modo de desarrollador** → **Cargar descomprimida** →
   carpeta `extension/`.
2. En la app: modo de conexión = **Extensión de Chrome**.
3. Recarga la pestaña de la clase (subtítulos activados). Debe aparecer
   *“✓ señal recibida”* → **▶ Iniciar**.

Detalles en `extension/README.md`.

### Modo alternativo: enganchar a tu propio Chrome (CDP)

Si prefieres usar tu Chrome habitual en vez del navegador propio:

1. `start-chrome-debug.bat` (abre Chrome con depuración en el puerto 9222).
2. En la app: **Modo de conexión → “Enganchar a mi Chrome (CDP :9222)”**.
3. Pulsa **↻** junto a *Pestaña abierta* y elige la pestaña de la clase.

## Cómo funciona

```
run.py ──> FastAPI (backend/main.py)
             ├─ backend/capture.py    Playwright: abre/engancha la página, lee el DOM
             ├─ backend/pipeline.py   detecta texto nuevo, lo parte en frases
             ├─ backend/translate.py  Argos Translate (offline)
             └─ WebSocket /ws ──────> frontend/ (dos columnas en vivo)
```

- **capture.py** relee cada ~1 s el `innerText` del contenedor de subtítulos.
- **pipeline.py** compara con lo ya visto (prefijo común), separa frases
  completas y deja la última como “interina” hasta que se cierra por puntuación
  o por pausa (`idle_flush`).
- **translate.py** traduce cada frase; los pares instalados funcionan sin red.

## Ajustes (`config.json`, se crea solo)

| Campo           | Descripción                                            |
|-----------------|-------------------------------------------------------|
| `attach_mode`   | `launch` (navegador propio) o `cdp`                    |
| `target_url`    | URL de la clase                                        |
| `selector`      | CSS del panel; vacío = automático                      |
| `poll_interval` | cada cuántos segundos se relee el DOM                  |
| `idle_flush`    | segundos de pausa para cerrar una frase incompleta     |
| `from_code` / `to_code` | códigos de idioma (`en`, `es`, `pt`, …)        |

## Notas

- La UPC/class.com puede requerir login: hazlo en la ventana de captura.
- Si “no se encuentra el contenedor de subtítulos”, usa **Elegir en la página**
  o mira el HTML del panel (F12) y pon el selector a mano.
- Nada sale de tu equipo: no hay llamadas a servicios externos en tiempo de uso.
