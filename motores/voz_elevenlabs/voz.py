"""
Motor de voz: ElevenLabs, con marcas de tiempo por palabra.

Hace lo mismo que motores/voz_cartesia/voz.py y devuelve LO MISMO -- un wav PCM
s16le mono a 44,1 kHz y una lista [{"w","s","e"}] de palabras con tiempos
absolutos -- para que el paso de voz y todo lo de aguas abajo no se enteren de
quien ha locutado.

Tres diferencias con Cartesia que explican el codigo
----------------------------------------------------
1. ElevenLabs da las marcas POR CARACTER (`alignment`), no por palabra. Aqui se
   agrupan en palabras cortando por espacios. Las etiquetas <break .../> se
   saltan por si vienen dentro del alineado: una etiqueta contada como palabra
   se comeria una palabra real y correria todos los cortes de plano.
2. No hay "contextos" como en Cartesia. La continuidad entre trozos se pide con
   `previous_request_ids` (los ids de las peticiones anteriores, hasta 3), y
   los tiempos de cada trozo empiezan en cero: se desplazan aqui.
3. El PCM a 44,1 kHz solo lo da a partir del plan Pro. Se pide y, si la cuenta
   no llega, se pide a 24 kHz y se remuestrea con ffmpeg a 44,1 kHz, que es la
   frecuencia con la que trabaja todo el Estudio.

Configuracion
-------------
Se lee por CONTRATO de secretos/elevenlabs.json (nunca importando codigo del
Estudio):

    {"activo": true, "clave": "sk_...", "voz_id": "...",
     "modelo": "eleven_multilingual_v2",
     "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}

`activo: false` (o borrar el fichero) vuelve a Cartesia. La clave tambien
puede venir de ELEVENLABS_API_KEY y la voz de ELEVENLABS_VOZ_ID.
"""
import base64
import json
import os
import re
import shutil
import struct
import subprocess

import requests

API = "https://api.elevenlabs.io/v1/text-to-speech/{voz}/with-timestamps"
SR = 44100
MODELO_POR_DEFECTO = "eleven_multilingual_v2"

#: Caracteres por peticion. La documentacion da 10.000 para multilingual_v2,
#: 40.000 para flash_v2_5 y 5.000 para v3; se deja margen por las etiquetas.
MAX_CARACTERES = {"eleven_multilingual_v2": 9000, "eleven_flash_v2_5": 9000,
                  "eleven_v3": 4500}

#: Rango de speed que acepta ElevenLabs en voice_settings.
SPEED_MIN, SPEED_MAX = 0.7, 1.2

CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")
RUTA_CONFIG = os.path.join(CARPETA_SECRETOS, "elevenlabs.json")

#: Se recuerda que esta cuenta no da 44,1 kHz para no pedirlo en cada trozo.
_SOLO_24K = {"valor": False}


def configuracion():
    """El contenido de secretos/elevenlabs.json con el entorno encima. -> dict"""
    datos = {}
    if os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, "r", encoding="utf-8-sig") as fh:
                crudo = json.load(fh)
            if isinstance(crudo, dict):
                datos = crudo
        except (OSError, ValueError):
            datos = {}
    if os.environ.get("ELEVENLABS_API_KEY"):
        datos["clave"] = os.environ["ELEVENLABS_API_KEY"]
    if os.environ.get("ELEVENLABS_VOZ_ID"):
        datos["voz_id"] = os.environ["ELEVENLABS_VOZ_ID"]
    return datos


def activo():
    """True si hay que locutar con ElevenLabs en vez de con Cartesia."""
    # las suites lo apagan: sus tomas reales comprueban Cartesia y no deben
    # gastar creditos de ElevenLabs
    if os.environ.get("ESTUDIO_SIN_ELEVENLABS"):
        return False
    cfg = configuracion()
    return bool(cfg.get("activo", True) and str(cfg.get("clave") or "").strip()
                and str(cfg.get("voz_id") or "").strip())


def cargar_api_key():
    clave = str(configuracion().get("clave") or "").strip()
    if not clave:
        raise SystemExit(f"No encuentro la clave de ElevenLabs. Ponla en "
                         f"{RUTA_CONFIG} o en ELEVENLABS_API_KEY.")
    return clave


def wav_desde_pcm(pcm: bytes) -> bytes:
    """Cabecera WAV PCM s16le mono a 44,1 kHz sobre PCM crudo."""
    cabecera = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    cabecera += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16)
    cabecera += b"data" + struct.pack("<I", len(pcm))
    return cabecera + pcm


# ------------------------------------------------------------------- audio

def _ffmpeg():
    ruta = os.environ.get("ESTUDIO_FFMPEG") or shutil.which("ffmpeg")
    if not ruta:
        raise RuntimeError("hace falta ffmpeg para pasar la voz de ElevenLabs "
                           "a 44,1 kHz y no lo encuentro en el PATH")
    return ruta


def remuestrear(pcm, desde_sr):
    """PCM s16le mono de desde_sr a 44,1 kHz, con ffmpeg."""
    if desde_sr == SR:
        return pcm
    proceso = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error",
         "-f", "s16le", "-ar", str(desde_sr), "-ac", "1", "-i", "pipe:0",
         "-af", "aresample=resampler=soxr",
         "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"],
        input=pcm, capture_output=True, check=False)
    if proceso.returncode != 0 or not proceso.stdout:
        # sin soxr compilado se reintenta con el remuestreador de serie
        proceso = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-loglevel", "error",
             "-f", "s16le", "-ar", str(desde_sr), "-ac", "1", "-i", "pipe:0",
             "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"],
            input=pcm, capture_output=True, check=False)
    if proceso.returncode != 0 or not proceso.stdout:
        raise RuntimeError("ffmpeg no ha podido remuestrear la voz: "
                           + proceso.stderr.decode("utf-8", "replace")[:300])
    return proceso.stdout[:len(proceso.stdout) & ~1]


# ------------------------------------------------------------------ marcas

def palabras_de_alineado(alineado, desde=0.0):
    """Marcas por caracter -> [{"w","s","e"}] por palabra, desplazadas `desde`.

    Lo que va entre < y > no es habla: se salta entero.
    """
    caracteres = alineado.get("characters") or []
    inicios = alineado.get("character_start_times_seconds") or []
    finales = alineado.get("character_end_times_seconds") or []
    palabras, actual, ini, fin = [], [], None, None
    en_etiqueta = False

    def cerrar():
        if actual:
            palabras.append({"w": "".join(actual), "s": round(ini + desde, 3),
                             "e": round(fin + desde, 3)})

    for caracter, s, e in zip(caracteres, inicios, finales):
        if caracter == "<":
            en_etiqueta = True
            continue
        if en_etiqueta:
            if caracter == ">":
                en_etiqueta = False
            continue
        if caracter.isspace():
            cerrar()
            actual, ini, fin = [], None, None
            continue
        if not actual:
            ini = s
        actual.append(caracter)
        fin = e
    cerrar()
    return palabras


# ------------------------------------------------------------------ trocear

_FIN_FRASE = re.compile(r"(?<=[.!?…»\"])\s+")


def partir(texto, maximo):
    """Parte un texto largo en trozos <= maximo, en fin de frase."""
    texto = texto.strip()
    if len(texto) <= maximo:
        return [texto] if texto else []
    trozos, actual = [], ""
    for frase in _FIN_FRASE.split(texto):
        if actual and len(actual) + 1 + len(frase) > maximo:
            trozos.append(actual)
            actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual:
        trozos.append(actual)
    # una frase sola de mas de `maximo` se corta por espacios
    salida = []
    for trozo in trozos:
        while len(trozo) > maximo:
            corte = trozo.rfind(" ", 0, maximo)
            corte = corte if corte > 0 else maximo
            salida.append(trozo[:corte].strip())
            trozo = trozo[corte:].strip()
        if trozo:
            salida.append(trozo)
    return salida


# ------------------------------------------------------------------ llamada

def _peticion(api_key, voz_id, modelo, idioma, texto, ajustes, anteriores,
              formato):
    cuerpo = {"text": texto, "model_id": modelo}
    if idioma and modelo != "eleven_multilingual_v2":
        # multilingual_v2 deduce el idioma del texto y rechaza language_code
        cuerpo["language_code"] = idioma
    if ajustes:
        cuerpo["voice_settings"] = ajustes
    if anteriores:
        cuerpo["previous_request_ids"] = anteriores[-3:]
    return requests.post(API.format(voz=voz_id),
                         params={"output_format": formato},
                         headers={"xi-api-key": api_key,
                                  "Content-Type": "application/json"},
                         json=cuerpo, timeout=(30, 600))


def _una(api_key, voz_id, modelo, idioma, texto, ajustes, anteriores):
    """Un trozo -> (pcm a 44,1 kHz, alineado, request_id)."""
    formatos = ["pcm_24000"] if _SOLO_24K["valor"] else ["pcm_44100", "pcm_24000"]
    ultimo = None
    for formato in formatos:
        respuesta = _peticion(api_key, voz_id, modelo, idioma, texto, ajustes,
                              anteriores, formato)
        if respuesta.status_code == 200:
            datos = respuesta.json()
            pcm = base64.b64decode(datos.get("audio_base64") or "")
            pcm = pcm[:len(pcm) & ~1]
            if formato == "pcm_24000":
                pcm = remuestrear(pcm, 24000)
            return (pcm, datos.get("alignment") or {},
                    respuesta.headers.get("request-id"))
        ultimo = respuesta
        # 44,1 kHz fuera del plan: se recuerda y se baja a 24 kHz. Cualquier
        # otro fallo no se arregla cambiando de formato.
        cuerpo = respuesta.text.lower()
        if formato == "pcm_44100" and respuesta.status_code in (400, 401, 403) \
                and ("output_format" in cuerpo or "tier" in cuerpo
                     or "subscription" in cuerpo or "pcm" in cuerpo):
            _SOLO_24K["valor"] = True
            continue
        break
    raise RuntimeError(f"ElevenLabs HTTP {ultimo.status_code}: {ultimo.text[:300]}")


def locutar(trozos, voz_id=None, modelo=None, idioma="es", ajustes=None,
            progreso=None):
    """Varios trozos de una misma toma -> (wav, duracion, palabras).

    Cada trozo se pide con los ids de los anteriores para que la entonacion
    siga, y sus marcas se desplazan por lo que ya se lleva grabado: la salida
    es una toma continua con tiempos absolutos, como la de Cartesia.
    """
    cfg = configuracion()
    api_key = cargar_api_key()
    voz_id = voz_id or str(cfg.get("voz_id") or "").strip()
    modelo = modelo or cfg.get("modelo") or MODELO_POR_DEFECTO
    maximo = MAX_CARACTERES.get(modelo, 4500)

    piezas = []
    for trozo in trozos:
        piezas.extend(partir(trozo, maximo))
    piezas = [p for p in piezas if p]
    if not piezas:
        raise ValueError("no hay texto que locutar")

    pcm_total, palabras, ids = [], [], []
    reloj = 0.0
    for numero, pieza in enumerate(piezas, 1):
        pcm, alineado, request_id = _una(api_key, voz_id, modelo, idioma,
                                         pieza, ajustes, ids)
        palabras.extend(palabras_de_alineado(alineado, desde=reloj))
        pcm_total.append(pcm)
        reloj += len(pcm) / (SR * 2)
        if request_id:
            ids.append(request_id)
        if callable(progreso):
            progreso(numero / len(piezas),
                     f"ElevenLabs: trozo {numero} de {len(piezas)}")

    crudo = b"".join(pcm_total)
    if not crudo:
        raise RuntimeError("ElevenLabs devolvio la toma sin audio")
    if not palabras:
        raise RuntimeError("ElevenLabs devolvio audio sin marcas de palabra: "
                           "sin marcas no se puede sincronizar el montaje")
    return wav_desde_pcm(crudo), len(crudo) / (SR * 2), palabras


def main():
    """Prueba suelta: python voz.py "Hola, esto es una prueba." salida.wav"""
    import sys
    texto = sys.argv[1] if len(sys.argv) > 1 else "Hola. Esto es una prueba de voz."
    destino = sys.argv[2] if len(sys.argv) > 2 else "prueba_elevenlabs.wav"
    wav, duracion, palabras = locutar([texto])
    with open(destino, "wb") as fh:
        fh.write(wav)
    print(f"{duracion:.2f}s -> {destino}")
    for p in palabras:
        print(f"  {p['s']:6.2f} {p['e']:6.2f}  {p['w']}")


if __name__ == "__main__":
    main()
