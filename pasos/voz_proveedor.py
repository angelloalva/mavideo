"""Quien locuta: Cartesia (el de fabrica) o ElevenLabs.

El motor de ElevenLabs (motores/voz_elevenlabs/voz.py) lee su configuracion
de `secretos/elevenlabs.json` por contrato, sin importar nada del Estudio:

    {"activo": true, "clave": "sk_...", "voz_id": "...",
     "modelo": "eleven_multilingual_v2",
     "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}

Este modulo es lo que la pantalla de Configuracion lee y escribe de ese
fichero. `activo` es el interruptor entre los dos proveedores: en falso se
vuelve a Cartesia sin perder la clave ni la voz de ElevenLabs, y al reves.

LA CLAVE NO BAJA AL NAVEGADOR. Se ensena tapada (`claves.tapar`) y guardar sin
clave nueva conserva la que habia, igual que el resto de claves.

Solo usa la biblioteca estandar y `claves`: la pantalla de ajustes tiene que
poder leerse aunque un motor pesado rompa la carga de los pasos.
"""
import json
import os
import tempfile

try:
    from . import claves
except ImportError:  # ejecutado con la carpeta pasos en sys.path
    import claves

#: Los modelos de ElevenLabs que el motor sabe trocear (ver MAX_CARACTERES alli).
MODELOS = ("eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_v3")
MODELO_POR_DEFECTO = "eleven_multilingual_v2"


def ruta():
    """La misma ruta que lee el motor: se resuelve en cada llamada porque las
    suites redirigen ESTUDIO_SECRETOS despues de importar."""
    carpeta = os.environ.get("ESTUDIO_SECRETOS") or claves.CARPETA_SECRETOS
    return os.path.join(carpeta, "elevenlabs.json")


def _leer_fichero():
    try:
        with open(ruta(), "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def configuracion():
    """El fichero tal cual, CON la clave. Solo para el servidor."""
    return _leer_fichero()


def elevenlabs_activo(datos=None):
    """Lo mismo que decide el motor: activo, con clave y con voz."""
    datos = _leer_fichero() if datos is None else datos
    return bool(datos.get("activo", True)
                and str(datos.get("clave") or "").strip()
                and str(datos.get("voz_id") or "").strip())


def leer():
    """Lo que ve la pantalla: el proveedor en uso y ElevenLabs sin su clave."""
    datos = _leer_fichero()
    clave = str(datos.get("clave") or "").strip()
    return {
        "proveedor": "elevenlabs" if elevenlabs_activo(datos) else "cartesia",
        "elevenlabs": {
            "tiene_clave": bool(clave),
            "clave": claves.tapar(clave) if clave else "",
            "voz_id": str(datos.get("voz_id") or "").strip(),
            "modelo": str(datos.get("modelo") or MODELO_POR_DEFECTO),
            "modelos": list(MODELOS),
            # encendido en el fichero aunque le falte algo para locutar
            "pedido": bool(datos.get("activo", False)),
        },
    }


def guardar(peticion):
    """Mezcla lo pedido sobre el fichero y lo escribe. -> leer()

    peticion: {"proveedor": "cartesia"|"elevenlabs",
               "elevenlabs": {"clave", "voz_id", "modelo"}}
    Una clave vacia o `claves.CONSERVAR` deja la que habia.
    """
    if not isinstance(peticion, dict):
        raise ValueError("la configuracion de voz se cambia con un objeto")
    datos = _leer_fichero()
    eleven = peticion.get("elevenlabs") or {}
    if not isinstance(eleven, dict):
        raise ValueError("'elevenlabs' tiene que ser un objeto")
    clave = str(eleven.get("clave") or "").strip()
    if clave and clave != claves.CONSERVAR:
        datos["clave"] = clave
    if "voz_id" in eleven:
        datos["voz_id"] = str(eleven.get("voz_id") or "").strip()
    if "modelo" in eleven:
        modelo = str(eleven.get("modelo") or "").strip() or MODELO_POR_DEFECTO
        if modelo not in MODELOS:
            raise ValueError(f"modelo {modelo!r}: solo {', '.join(MODELOS)}")
        datos["modelo"] = modelo
    proveedor = peticion.get("proveedor")
    if proveedor is not None:
        if proveedor not in ("cartesia", "elevenlabs"):
            raise ValueError(f"proveedor {proveedor!r}: cartesia o elevenlabs")
        datos["activo"] = proveedor == "elevenlabs"
        if datos["activo"] and not elevenlabs_activo(datos):
            raise ValueError("para locutar con ElevenLabs hacen falta su clave "
                             "y el id de la voz")
    datos.setdefault("modelo", MODELO_POR_DEFECTO)
    datos.setdefault("voice_settings", {"stability": 0.5,
                                        "similarity_boost": 0.75, "style": 0.0})
    destino = ruta()
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=".elevenlabs_", suffix=".json",
                                    dir=os.path.dirname(destino))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
    os.replace(temporal, destino)
    return leer()
