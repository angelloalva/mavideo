"""Lo que la pantalla lee y escribe de Google Vertex (las imagenes con Nano Banana).

El motor (motores/imagen_vertex/vertex.py) lee por contrato dos ficheros de
`secretos/`, y este modulo es quien los escribe desde Configuracion:

    vertex_cuenta.json   la clave de la cuenta de servicio, TAL CUAL la da la
                         consola de Google Cloud (IAM > Cuentas de servicio >
                         Claves > Anadir clave > JSON)
    vertex.json          {"modelo", "ubicacion", "proyecto"}

LA CLAVE NO BAJA AL NAVEGADOR. Se sube una vez y lo unico que vuelve es el
correo de la cuenta y el proyecto, que es lo que sirve para saber cual hay.

Solo biblioteca estandar y `claves`: la pantalla de ajustes tiene que poder
leerse aunque un motor pesado rompa la carga de los pasos.
"""
import importlib.util
import json
import os
import tempfile

try:
    from . import claves
except ImportError:  # ejecutado con la carpeta pasos en sys.path
    import claves

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Los modelos de imagen de Gemini que se ofrecen. El primero es el estable
#: («Nano Banana»); se puede escribir otro si Google saca uno nuevo.
MODELOS = ("gemini-2.5-flash-image", "gemini-3.1-flash-image-preview")
MODELO_POR_DEFECTO = MODELOS[0]
UBICACION_POR_DEFECTO = "global"


def _carpeta():
    return os.environ.get("ESTUDIO_SECRETOS") or claves.CARPETA_SECRETOS


def ruta_cuenta():
    return os.path.join(_carpeta(), "vertex_cuenta.json")


def ruta_config():
    return os.path.join(_carpeta(), "vertex.json")


def _leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=".vertex_", suffix=".json",
                                    dir=os.path.dirname(ruta))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)


def leer():
    """Lo que ve la pantalla. Sin ninguna clave."""
    cuenta = _leer(ruta_cuenta())
    config = _leer(ruta_config())
    proyecto = str(config.get("proyecto") or cuenta.get("project_id") or "")
    return {
        "listo": bool(cuenta.get("private_key") and cuenta.get("client_email")
                      and proyecto),
        "cuenta": ({"correo": cuenta.get("client_email", ""),
                    "proyecto": cuenta.get("project_id", "")}
                   if cuenta.get("client_email") else None),
        "proyecto": proyecto,
        "modelo": str(config.get("modelo") or MODELO_POR_DEFECTO),
        "ubicacion": str(config.get("ubicacion") or UBICACION_POR_DEFECTO),
        "modelos": list(MODELOS),
    }


def guardar(peticion):
    """Guarda la cuenta de servicio y/o el modelo, la ubicacion y el proyecto.

    peticion: {"cuenta_json": "<el .json entero>", "modelo", "ubicacion",
               "proyecto"}. -> leer()
    """
    if not isinstance(peticion, dict):
        raise ValueError("la configuracion de Vertex se cambia con un objeto")
    texto = peticion.get("cuenta_json")
    if texto:
        try:
            cuenta = json.loads(texto) if isinstance(texto, str) else dict(texto)
        except ValueError:
            raise ValueError("eso no es un .json: sube el fichero de la clave "
                             "tal cual lo descarga Google Cloud")
        if cuenta.get("type") != "service_account" or not cuenta.get("private_key") \
                or not cuenta.get("client_email"):
            raise ValueError("ese .json no es la clave de una CUENTA DE SERVICIO "
                             "(le falta type=service_account, private_key o "
                             "client_email)")
        _escribir(ruta_cuenta(), cuenta)
    config = _leer(ruta_config())
    for clave in ("modelo", "ubicacion", "proyecto"):
        if clave in peticion:
            valor = str(peticion.get(clave) or "").strip()
            if valor:
                config[clave] = valor
            else:
                config.pop(clave, None)
    _escribir(ruta_config(), config)
    return leer()


def probar():
    """Le habla a Vertex sin generar nada (countTokens no se cobra)."""
    ruta = os.path.join(RAIZ, "motores", "imagen_vertex", "vertex.py")
    spec = importlib.util.spec_from_file_location("_vertex_probar", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.probar()
