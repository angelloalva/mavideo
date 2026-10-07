# Integración de Clips de Vídeo Animados (Google Flow Video)

## Resumen de la Funcionalidad

Permite incorporar clips animados generados manualmente en **Google Flow Video** (clips estándar de 8 segundos) en escenas específicas del vídeo, detectadas de forma automática mediante etiquetas semánticas en el guión (`FLOW #1` a `FLOW #8`, `[CUARTA PARED]`, prompts en inglés de Flow) o asignadas manualmente desde la interfaz web.

---

## Flujo de Trabajo

### 1. Detección automática en el guión
Al planificar las escenas (`pasos/p6_assets.py`), el sistema lee el material de ingesta y localiza:
- Las etiquetas `FLOW #N` y los bloques de prompts en inglés (`Using the reference image... 8 seconds.`).
- Los efectos especiales como `[CUARTA PARED]`.
- Empareja automáticamente cada clip con la escena correspondiente por afinidad y palabras clave de la narración.
- Exporta en la carpeta del proyecto:
  - `flow/prompts_video.txt`: listado ordenado con los prompts listos para copiar a Flow y el nombre de archivo recomendado.
  - `flow/videos.json`: manifiesto con estado de cada clip (presente / pendiente).

### 2. Guardado o subida de los archivos de vídeo
Tienes dos formas sencillas de incorporar los vídeos:
- **Desde la interfaz web (`http://127.0.0.1:8020/`):**
  - En la pestaña de escenas (o modo Light), cada plano que corresponda a Flow muestra una tarjeta `🎬 Clip animado Flow #N`, con el botón **«📋 Copiar prompt para Flow»** y el botón **«📤 Subir clip .mp4»**.
  - Al subir el archivo, se guarda directamente y se genera su fotograma póster automáticamente.
- **Directamente en disco:**
  - Guarda los clips `.mp4` en la carpeta `flow/videos/` del proyecto con el nombre del clip o escena:
    - Ejemplo: `flow_1.mp4`, `flow_2.mp4` o `S001.mp4`, `S005.mp4`.

### 3. Visualización y reproducción en la interfaz
- En la cuadrícula de escenas (`⊞ Ver todas`), las escenas con vídeo animado llevan una insignia `🎬 #N`.
- En la vista individual, la tarjeta muestra el reproductor `<video>` con reproducción fluida y los badges correspondientes (`🎬 FLOW #N` y `CUARTA PARED`).

### 4. Renderizado y Conformado en el montaje (`pasos/p8_render.py`)
- **Ajuste temporal inteligente:** Si la locución dura más de 8 segundos, el render clona suavemente el último fotograma (`tpad=stop_mode=clone`) hasta cubrir la duración exacta de la voz. Si dura menos, lo recorta con precisión.
- **Ruta rápida (Fast-path):** Si la escena no tiene subtítulos ni rótulos superpuestos ni transición de entrada, FFmpeg compila el clip directamente en 0.2 segundos sin invocar Edge headless.
- **Ruta con subtítulos/capas:** Si la escena incluye subtítulos o cartelas vectoriales, Edge headless captura los fotogramas con el vídeo de fondo y el overlay tipográfico superpuesto a máxima resolución.
- **Transiciones continuas:** El último fotograma del vídeo se extrae siempre como referencia para que las transiciones hacia la escena siguiente funcionen a la perfección.
- **Detección de cambios:** Si se sustituye un archivo `.mp4`, `unidades_pendientes()` detecta que el vídeo es más reciente que el clip previo y programa el plano para actualizarse.
