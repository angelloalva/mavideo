"""Lo que hace falta para SUBIR el video: titulo, descripcion, etiquetas y creditos.

LOS CREDITOS NO SON OPCIONALES. La musica (Jamendo) y los efectos (Freesound)
que entran en un video solo pueden ser CC0 o CC BY (`sonido.licencia_comercial`),
y CC BY obliga a citar autor, obra y licencia donde se publica. Aqui se sacan de
lo que el render tiene de verdad en sus params -- los temas de cada tramo y los
efectos surtidos para este video -- y se escriben en un bloque listo para pegar
en la descripcion. Los CC0 no piden nada y no se ponen.

Los efectos se citan TODOS los surtidos para el video, no solo los que acaban
sonando: el render los reparte por semilla y saber cual cayo en que corte
obligaria a repetir su cuenta. Citar de mas no incumple ninguna licencia;
citar de menos, si.

EL TITULO Y LA DESCRIPCION los propone el CLI de Claude a partir del guion
(sonnet, esfuerzo bajo: por la suscripcion, sin coste por uso). Se guardan en
`proyectos/<id>/publicacion.json` y en `publicacion.txt`, que se puede abrir
sin la app.
"""
import json
import os
import re

try:
    from . import cli_claude, comun
except ImportError:  # ejecutado con la carpeta pasos en sys.path
    import cli_claude
    import comun

NOMBRE_JSON = "publicacion.json"
NOMBRE_TXT = "publicacion.txt"


def nombre_licencia(url):
    """«CC BY 4.0», «CC0 1.0»... a partir de la URL de la licencia."""
    u = str(url or "").lower()
    if "publicdomain/zero" in u:
        m = re.search(r"zero/([\d.]+)", u)
        return f"CC0 {m.group(1)}" if m else "CC0"
    m = re.search(r"/licenses/([a-z+-]+)/([\d.]+)", u)
    if m:
        return f"CC {m.group(1).upper()} {m.group(2)}"
    return str(url or "licencia desconocida")


def pide_credito(url):
    """Si esa licencia obliga a citar (todo lo que no es CC0)."""
    return "publicdomain/zero" not in str(url or "").lower()


def creditos(render):
    """Lo que suena en el video y pide credito. -> [ficha]"""
    render = render or {}
    salida, vistos = [], set()
    for tramo in ((render.get("musica") or {}).get("tramos") or []):
        clave = ("musica", str(tramo.get("id")))
        if clave in vistos or not pide_credito(tramo.get("licencia")):
            continue
        vistos.add(clave)
        salida.append({
            "tipo": "música", "titulo": tramo.get("titulo") or "",
            "autor": tramo.get("artista") or "",
            "licencia": nombre_licencia(tramo.get("licencia")),
            "licencia_url": tramo.get("licencia") or "",
            "url": (f"https://www.jamendo.com/track/{tramo.get('id')}"
                    if tramo.get("fuente") == "jamendo" and tramo.get("id") else ""),
        })
    for fichas in (render.get("efectos") or {}).values():
        for ficha in fichas or []:
            clave = ("efecto", str(ficha.get("id")))
            if clave in vistos or not pide_credito(ficha.get("licencia")):
                continue
            vistos.add(clave)
            salida.append({
                "tipo": "efecto", "titulo": ficha.get("titulo") or "",
                "autor": ficha.get("autor") or "",
                "licencia": nombre_licencia(ficha.get("licencia")),
                "licencia_url": ficha.get("licencia") or "",
                "url": ficha.get("pagina") or "",
            })
    return salida


def texto_creditos(fichas):
    """El bloque para pegar al final de la descripcion. -> texto ('' si nada)"""
    musica = [f for f in fichas if f["tipo"] == "música"]
    efectos = [f for f in fichas if f["tipo"] == "efecto"]
    lineas = []

    def linea(f):
        return (f"«{f['titulo']}» – {f['autor']} · {f['licencia']}"
                + (f" · {f['url']}" if f["url"] else ""))

    if musica:
        lineas.append("Música (jamendo.com):")
        lineas.extend(linea(f) for f in musica)
    if efectos:
        if lineas:
            lineas.append("")
        lineas.append("Efectos de sonido (freesound.org):")
        lineas.extend(linea(f) for f in efectos)
    return "\n".join(lineas)


def _guion(proyecto):
    guion = comun.leer_salida(proyecto, "guion", "guion.json", obligatorio=False) or {}
    return "\n".join(str(b.get("texto") or b.get("narracion") or "")
                     for b in guion.get("guion") or []).strip()


def proponer(proyecto, titulo_trabajo, idioma="es", avisar=None):
    """Titulos, descripcion y etiquetas para YouTube, sacados del guion. -> dict"""
    avisar = avisar or (lambda *a, **k: None)
    texto = _guion(proyecto)
    if not texto:
        raise RuntimeError("no hay guion del que sacar el título y la descripción")
    # las pausas marcadas para la voz no son texto
    texto = re.sub(r"<[^>]+>", " ", texto)
    avisar(0.1, "pidiendo a Claude título, descripción y etiquetas")
    instruccion = (
        "Vas a preparar la ficha de YouTube de un video narrado. Contesta SOLO "
        "con un objeto JSON, sin nada antes ni despues, con estas claves:\n"
        '  "titulos": 4 titulos distintos, de menos de 70 caracteres, que den '
        "ganas de verlo sin mentir sobre lo que cuenta;\n"
        '  "descripcion": 2-3 parrafos cortos que resuman de que va el video y '
        "por que merece la pena, sin enlaces, sin hashtags y sin inventar nada "
        "que no diga el guion;\n"
        '  "etiquetas": entre 8 y 15 etiquetas cortas, en minusculas.\n'
        f"Todo en el idioma del guion (codigo: {idioma}).\n\n"
        f"TITULO DE TRABAJO: {titulo_trabajo}\n\nGUION:\n{texto[:12000]}")
    respuesta, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="low",
                                       para="la ficha de YouTube")
    crudo = str(respuesta or "")
    inicio, fin = crudo.find("{"), crudo.rfind("}")
    try:
        datos = json.loads(crudo[inicio:fin + 1])
    except ValueError:
        raise RuntimeError("Claude no ha devuelto la ficha en el formato pedido; "
                           "vuelve a intentarlo")
    avisar(0.9, "ficha lista")
    return {"titulos": [str(t).strip() for t in datos.get("titulos") or []][:6],
            "descripcion": str(datos.get("descripcion") or "").strip(),
            "etiquetas": [str(t).strip() for t in datos.get("etiquetas") or []][:20]}


def leer(proyecto):
    """La ficha guardada, o None."""
    try:
        with open(os.path.join(proyecto.raiz, NOMBRE_JSON), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def guardar(proyecto, propuesta, fichas):
    """Escribe publicacion.json y publicacion.txt en la carpeta del proyecto."""
    bloque = texto_creditos(fichas)
    ficha = dict(propuesta, creditos=fichas, texto_creditos=bloque)
    with open(os.path.join(proyecto.raiz, NOMBRE_JSON), "w", encoding="utf-8") as fh:
        json.dump(ficha, fh, ensure_ascii=False, indent=2)
    partes = ["TÍTULOS PROPUESTOS"] + [f"- {t}" for t in propuesta.get("titulos") or []]
    partes += ["", "DESCRIPCIÓN", propuesta.get("descripcion") or ""]
    if bloque:
        partes += ["", bloque]
    partes += ["", "ETIQUETAS", ", ".join(propuesta.get("etiquetas") or [])]
    with open(os.path.join(proyecto.raiz, NOMBRE_TXT), "w", encoding="utf-8") as fh:
        fh.write("\n".join(partes) + "\n")
    return ficha
