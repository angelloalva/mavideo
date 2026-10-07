"""Las imagenes hechas a mano en Google Flow, en vez de generadas con OpenAI.

QUE ES ESTE MODO
----------------
El paso de assets sabe ADOPTAR arte que ya existe (`motor_imagen: "adoptar"`):
no genera nada, busca `<id>.png` en `imagenes_previas` y lo usa, a coste cero.
Este modulo es lo que hay alrededor para que ese arte salga de Flow:

  1. EXPORTAR  el prompt de cada plano que necesita imagen, con una FRASE DE
               ESTILO delante, en `proyectos/<id>/flow/`:
                 prompts.txt  para leerlo o copiarlo a mano
                 tanda.json   lo que carga la extension de Chrome
                              (herramientas/flow_extension)
                 planos.json  los ids en orden, con su frase narrada
                 estilo.txt   la frase de estilo, fija para todo el video
  2. IMPORTAR  lo descargado de Flow (la extension lo guarda como
               `Descargas/estudio_flow/<proyecto>/<id>.<ext>`) a
               `flow/imagenes/<id>.png`, recortado a 1536x1024.

Lo usan la pantalla (app.py, `/api/proyectos/{pid}/flow/*` y la tarea de los
planos de la receta) y los dos scripts de `herramientas/`, que son la misma
cosa por linea de comandos.

LA FRASE DE ESTILO. Los prompts del Estudio dicen QUE se ve en cada plano; COMO
se dibuja lo ponen normalmente las laminas de referencia que se adjuntan a
OpenAI. En Flow no hay adjuntos, asi que sin una frase fija cada imagen saldria
en un estilo. La primera vez se le pide al CLI de Claude (sonnet, esfuerzo
bajo: por la suscripcion, sin coste por uso) paleta y ambiente segun el guion,
sobre una base fija de ilustracion plana. Se guarda y NO se vuelve a pedir
salvo que se pida: cambiarla a mitad de video es justo la incoherencia que
existe para evitar.

LOS IDS SON POSICIONALES. Si despues de exportar cambian el guion, la voz o el
ritmo, S014 pasa a narrar otra cosa. Por eso se exporta con los params
GUARDADOS del paso -- los mismos que usara al ejecutarse -- y `planos.json`
guarda la frase de cada id para poder compararla.

UNA IMAGEN REHECHA EN FLOW NO SE VE SOLA. Adoptar no mueve la firma del plano:
si S014 ya estaba en la version activa, el paso lo da por hecho y no vuelve a
mirar `flow/imagenes`. `cambiadas()` compara fechas y dice que planos hay que
volver a adoptar, y quien ejecuta el paso se los pide por unidad.
"""
from __future__ import annotations

import json
import os
import re

try:
    from . import cartelas, cli_claude, p6_assets
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cartelas
    import cli_claude
    import p6_assets

#: Lo que no cambia de un video a otro: la tecnica. La paleta y el ambiente son
#: lo que se adapta al tema.
BASE_ESTILO = ("Flat 2D vector illustration, clean simple geometric shapes, "
               "no outlines, subtle grain texture, soft even lighting")

#: Lo que va SIEMPRE al final, lo proponga quien lo proponga: los generadores
#: meten letras deformes a la minima.
COLETILLA = "no text, no letters, no watermark"

#: El tamano con el que trabaja el Estudio (3:2). Flow da 16:9: se RECORTA al
#: centro (un 8 % por cada lado) en vez de estirar o meter bandas -- estirar
#: deforma, y una banda negra acabaria dentro del video.
TAMANO = (1536, 1024)
EXTENSIONES = (".png", ".jpg", ".jpeg", ".webp")

#: Lo que se le quita al prompt de un plano conceptual: remite a unas laminas
#: de referencia que en Flow no existen. La frase de estilo ya lo dice.
REMITE = ", in the exact same flat vector style as the rest of the video"


# ------------------------------------------------------------------ rutas

def carpeta_flow(ruta_proyecto):
    return os.path.join(ruta_proyecto, "flow")


def carpeta_imagenes(ruta_proyecto):
    return os.path.join(carpeta_flow(ruta_proyecto), "imagenes")


def carpeta_videos(ruta_proyecto):
    return os.path.join(carpeta_flow(ruta_proyecto), "videos")


def descargas_por_defecto():
    """Donde deja la extension las imagenes: Descargas/estudio_flow."""
    return os.path.join(os.path.expanduser("~"), "Downloads", "estudio_flow")


def carpeta_descargas(pid, base=None):
    """La carpeta de descargas de ESTE proyecto: <base>/<pid>."""
    return os.path.join(base or descargas_por_defecto(), pid)


def params_flow(ruta_proyecto):
    """Lo que el paso de assets necesita para adoptar lo que venga de Flow.

    El ritmo (min_s / max_s) NO va aqui: lo decide el deslizador de ritmo como
    en cualquier otro video. Cuantas imagenes hay que hacer depende de el.
    """
    return {"motor_imagen": "adoptar",
            "imagenes_previas": [carpeta_imagenes(ruta_proyecto)]}


def es_flow(params):
    """Si el paso de assets de este proyecto adopta en vez de generar."""
    return (params or {}).get("motor_imagen") == "adoptar"


# ------------------------------------------------------------------ exportar

def necesita_imagen(escena):
    """Las que el paso resolvera con un PNG propio no se piden (ver p6_assets:
    cartelas, segundas mitades y componentes no llevan imagen que adoptar)."""
    return not (cartelas.sin_imagen(escena) or escena.get("sigue_a")
                or escena.get("componente"))


def sugerir_estilo(narracion):
    """Le pide a Claude paleta y ambiente para ESTE guion. Una linea."""
    instruccion = (
        "Vas a proponer la frase de estilo visual que ira delante de TODOS los "
        "prompts de imagen de un video narrado. La tecnica es fija y tiene que "
        f"empezar exactamente asi: \"{BASE_ESTILO}\". Tu parte es anadir, en "
        "ingles, la PALETA (3-5 colores concretos) y el AMBIENTE que mejor le "
        "vayan al tema de este guion, en menos de 35 palabras mas. Nada de "
        "personajes ni de escenas concretas: solo como se dibuja. Contesta "
        "SOLO con la frase, en una linea, sin comillas.\n\nGUION:\n" + narracion)
    texto, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="low",
                                   para="la frase de estilo de Flow")
    frase = " ".join(str(texto or "").split()).strip().strip('"')
    if not frase.lower().startswith(BASE_ESTILO.lower()[:25]):
        frase = f"{BASE_ESTILO}, {frase}"
    return frase


def con_coletilla(frase):
    frase = frase.strip().rstrip(".")
    if "no text" not in frase.lower():
        frase = f"{frase}, {COLETILLA}"
    return frase + "."


def estilo_del_video(dir_flow, narracion, fijada=None, sugerir=False,
                     sin_claude=False, avisar=None):
    """La frase de estilo: la guardada, o una nueva si se pide o no hay."""
    ruta = os.path.join(dir_flow, "estilo.txt")
    if fijada:
        frase = con_coletilla(fijada)
    elif os.path.exists(ruta) and not sugerir:
        with open(ruta, encoding="utf-8") as fh:
            return fh.read().strip()
    elif sin_claude:
        frase = con_coletilla(BASE_ESTILO)
    else:
        if avisar:
            avisar("pidiendo a Claude una frase de estilo para este guion")
        frase = con_coletilla(sugerir_estilo(narracion))
    os.makedirs(dir_flow, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(frase + "\n")
    return frase


def prompt_hoja(ficha):
    """Hoja de personaje para Flow. La del Estudio (`p6_assets._prompt_reparto`)
    remite a una lamina de estilo adjunta que aqui no hay; esta dice lo mismo
    sin ella: bustos grandes arriba -- la cara es lo que la hoja tiene que fijar
    -- y cuerpo entero abajo, sobre fondo liso."""
    quien = ("these characters, each one clearly distinct"
             if ficha.get("grupo") else "this character")
    return (f"Character reference sheet of {quien}, on a plain flat light "
            f"background. Top row: large head-and-shoulders portraits, face "
            f"clearly visible, neutral expression. Bottom row: the same, full "
            f"body standing, front view, same order. "
            f"{ficha.get('descripcion', '').strip()}")


def exportar(proyecto, params, estilo_fijado=None, sugerir=False,
             sin_claude=False, avisar=None):
    """Escribe prompts.txt, tanda.json, planos.json y estilo.txt. -> dict

    `proyecto` es un `nucleo.Proyecto` y `params` los del paso de assets tal y
    como estan GUARDADOS: el plan tiene que ser el mismo que usara el paso.
    """
    ruta_proyecto = proyecto.raiz
    plan = p6_assets.planificar(proyecto, params)
    escenas = [e for e in plan["escenas"] if necesita_imagen(e)]
    if not escenas:
        raise RuntimeError("el plan no tiene ningun plano con imagen")

    dir_flow = carpeta_flow(ruta_proyecto)
    os.makedirs(carpeta_imagenes(ruta_proyecto), exist_ok=True)
    narracion = "\n".join(e.get("narracion") or "" for e in plan["escenas"])
    estilo = estilo_del_video(dir_flow, narracion, estilo_fijado, sugerir,
                              sin_claude, avisar)

    # LAS HOJAS DE PERSONAJE VAN PRIMERO. En modo adoptar el paso las exige
    # como cualquier plano (`<nombre>.png`), y en Flow sirven de ingrediente:
    # hechas antes, se pueden adjuntar en cada plano donde sale ese personaje.
    reparto = {f["nombre"]: f for f in (plan.get("assets") or {}).values()
               if f.get("tipo") == "reparto"}
    total = len(reparto) + len(escenas)
    bloques = [f"ESTILO (va delante de cada prompt):\n{estilo}\n",
               f"{total} imagenes, 16:9. Descargalas EN ESTE ORDEN."
               + (f" Las {len(reparto)} primeras son hojas de personaje: usalas "
                  f"como ingrediente en los planos donde sale cada uno.\n"
                  if reparto else "\n")]
    tanda = []
    for nombre, ficha in reparto.items():
        bloques.append(
            f"=== {nombre}  (hoja de personaje)\n\n"
            f"{estilo} {prompt_hoja(ficha)}\n")
        tanda.append({"id": nombre, "tipo": "hoja",
                      "narracion": "(hoja de personaje)",
                      "prompt": f"{estilo} {prompt_hoja(ficha)}"})
    for escena in escenas:
        prompt = " ".join((escena.get("prompt") or "").replace(REMITE, "").split())
        # el prompt nombra al reparto por su id («with the character
        # 'ptolomeo'»), que para Flow no significa nada: va la descripcion
        quienes = [reparto[n] for n in escena.get("personajes") or []
                   if n in reparto]
        extra = " ".join(f"Character '{f['nombre']}': {f['descripcion'].strip()}"
                         for f in quienes)
        ingredientes = (f"Ingrediente: hoja de "
                        f"{', '.join(f['nombre'] for f in quienes)}\n"
                        if quienes else "")
        bloques.append(
            f"=== {escena['id']}  ({escena.get('duracion', 0):.1f} s)\n"
            f"Narracion: {escena.get('narracion', '').strip()}\n"
            f"{ingredientes}\n"
            f"{estilo} {prompt} {extra}".rstrip() + "\n")
        tanda.append({"id": escena["id"], "tipo": "plano",
                      "narracion": escena.get("narracion", "").strip(),
                      "personajes": [f["nombre"] for f in quienes],
                      "prompt": f"{estilo} {prompt} {extra}".strip()})
    with open(os.path.join(dir_flow, "prompts.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(bloques))
    with open(os.path.join(dir_flow, "tanda.json"), "w", encoding="utf-8") as fh:
        json.dump({"proyecto": os.path.basename(os.path.normpath(ruta_proyecto)),
                   "imagenes": tanda}, fh, ensure_ascii=False, indent=1)
    planos = ([{"id": n, "narracion": "(hoja de personaje)"} for n in reparto]
              + [{"id": e["id"], "narracion": e.get("narracion", "")}
                 for e in escenas])
    with open(os.path.join(dir_flow, "planos.json"), "w", encoding="utf-8") as fh:
        json.dump({"planos": planos,
                   "sin_imagen": [e["id"] for e in plan["escenas"]
                                  if not necesita_imagen(e)]},
                  fh, ensure_ascii=False, indent=1)
    return {"planos": planos, "estilo": estilo, "dir_flow": dir_flow,
            "total": total, "hojas": len(reparto)}


def planos_exportados(ruta_proyecto):
    """Los planos de la ultima exportacion, o [] si no se ha exportado."""
    ruta = os.path.join(carpeta_flow(ruta_proyecto), "planos.json")
    try:
        with open(ruta, encoding="utf-8") as fh:
            return list(json.load(fh).get("planos") or [])
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------ importar

def imagenes_en(carpeta):
    """Las imagenes de la carpeta, la mas antigua primero."""
    if not os.path.isdir(carpeta):
        return []
    ficheros = [os.path.join(carpeta, f) for f in os.listdir(carpeta)
                if f.lower().endswith(EXTENSIONES)]
    return sorted(ficheros, key=lambda f: (os.path.getmtime(f), f))


def por_nombre(ficheros, ids):
    """[(id, fichero)] de los ficheros que se llaman como un plano.

    Sin distinguir mayusculas, y el MAS RECIENTE si hay dos con el mismo id y
    distinta extension: es el que se bajo al repetirlo."""
    bajos = {i.lower(): i for i in ids}
    parejas = {}
    for fichero in ficheros:                    # de mas antiguo a mas nuevo
        raiz = os.path.splitext(os.path.basename(fichero))[0].lower()
        if raiz in bajos:
            parejas[bajos[raiz]] = fichero
    return [(i, parejas[i]) for i in ids if i in parejas]


def encajar(origen, destino):
    """Recorta al centro hasta 3:2 y deja el PNG a 1536x1024."""
    from PIL import Image
    img = Image.open(origen).convert("RGB")
    objetivo = TAMANO[0] / TAMANO[1]
    if img.width / img.height > objetivo:
        ancho = round(img.height * objetivo)
        izq = (img.width - ancho) // 2
        img = img.crop((izq, 0, izq + ancho, img.height))
    else:
        alto = round(img.width / objetivo)
        arriba = (img.height - alto) // 2
        img = img.crop((0, arriba, img.width, arriba + alto))
    img.resize(TAMANO, Image.LANCZOS).save(destino, "PNG")


def _mas_nuevo(origen, destino):
    return (not os.path.exists(destino)
            or os.path.getmtime(origen) > os.path.getmtime(destino))


def estado(ruta_proyecto, descargas):
    """Cuantas imagenes hay y cuantas esperan en la carpeta de descargas."""
    planos = planos_exportados(ruta_proyecto)
    ids = [p["id"] for p in planos]
    dir_img = carpeta_imagenes(ruta_proyecto)
    listas = [i for i in ids if os.path.exists(os.path.join(dir_img, f"{i}.png"))]
    nuevas = [i for i, f in por_nombre(imagenes_en(descargas), ids)
              if _mas_nuevo(f, os.path.join(dir_img, f"{i}.png"))]
    return {"exportado": bool(ids), "total": len(ids), "listas": len(listas),
            "faltan": [i for i in ids if i not in listas],
            "por_importar": nuevas, "descargas": descargas,
            "tanda": os.path.join(carpeta_flow(ruta_proyecto), "tanda.json")}


def importar(ruta_proyecto, descargas):
    """Copia lo descargado que sea nuevo o mas reciente. -> {copiadas, ...}

    NO pisa nada que sea mas nuevo que la descarga, y los originales no se
    tocan: una imagen buena de Flow cuesta tiempo.
    """
    ids = [p["id"] for p in planos_exportados(ruta_proyecto)]
    if not ids:
        raise RuntimeError("todavia no se han preparado los prompts de Flow")
    dir_img = carpeta_imagenes(ruta_proyecto)
    os.makedirs(dir_img, exist_ok=True)
    copiadas = []
    for sid, fichero in por_nombre(imagenes_en(descargas), ids):
        destino = os.path.join(dir_img, f"{sid}.png")
        if _mas_nuevo(fichero, destino):
            encajar(fichero, destino)
            copiadas.append(sid)
    salida = estado(ruta_proyecto, descargas)
    salida["copiadas"] = copiadas
    return salida


def cambiadas(ruta_proyecto, carpeta_version):
    """Unidades de assets cuya imagen de Flow es mas nueva que la adoptada.

    -> ["escena:S014", "asset:ptolomeo", ...]. `carpeta_version` es la version
    activa del paso (`pasos/assets/v<N>`); sin ella no hay nada que comparar.
    """
    if not carpeta_version or not os.path.isdir(carpeta_version):
        return []
    dir_img = carpeta_imagenes(ruta_proyecto)
    salida = []
    for plano in planos_exportados(ruta_proyecto):
        sid = plano["id"]
        origen = os.path.join(dir_img, f"{sid}.png")
        if not os.path.exists(origen):
            continue
        hoja = plano.get("narracion") == "(hoja de personaje)"
        adoptada = (os.path.join(carpeta_version, "assets", "reparto", f"{sid}.png")
                    if hoja else os.path.join(carpeta_version, "escenas", f"{sid}.png"))
        if _mas_nuevo(origen, adoptada):
            salida.append(f"asset:{sid}" if hoja else f"escena:{sid}")
    return salida


# -------------------------------------------------------- videos animados (Flow)

def buscar_video_de_escena(ruta_proyecto, sid, flow_num=None):
    """Busca si este plano tiene un clip de video animado manual. -> ruta o None"""
    if not ruta_proyecto or not sid:
        return None
    c_videos = carpeta_videos(ruta_proyecto)
    c_anim = os.path.join(ruta_proyecto, "animaciones")
    candidatos = []
    # 1. Por ID directo de escena
    for base in (c_videos, c_anim):
        candidatos.extend([
            os.path.join(base, f"{sid}.mp4"),
            os.path.join(base, f"{sid.lower()}.mp4"),
            os.path.join(base, f"{sid.upper()}.mp4"),
        ])
    # 2. Cargar mapa estricto de videos.json si existe
    ruta_vjson = os.path.join(ruta_proyecto, "flow", "videos.json")
    mapa_clips = {}
    if os.path.isfile(ruta_vjson):
        try:
            with open(ruta_vjson, "r", encoding="utf-8") as fh:
                vdata = json.load(fh)
            for c in vdata.get("clips", []):
                if c.get("escena_id") and c.get("num") is not None:
                    mapa_clips[int(c["num"])] = str(c["escena_id"]).upper()
        except Exception:
            pass

    # 3. Determinar el número de Flow efectivo estrictamente asignado a este plano
    num_efectivo = None
    if flow_num is not None:
        try:
            n = int(flow_num)
            # Solo si en videos.json no está asignado a otra escena diferente
            if not mapa_clips or mapa_clips.get(n) == str(sid).upper():
                num_efectivo = n
        except (ValueError, TypeError):
            pass
    elif mapa_clips:
        for n, mapped_sid in mapa_clips.items():
            if mapped_sid == str(sid).upper():
                num_efectivo = n
                break

    if num_efectivo is not None:
        num = num_efectivo
        for base in (c_videos, c_anim):
            candidatos.extend([
                os.path.join(base, f"FLOW_{num}.mp4"),
                os.path.join(base, f"flow_{num}.mp4"),
                os.path.join(base, f"FLOW_{num:02d}.mp4"),
                os.path.join(base, f"flow_{num:02d}.mp4"),
                os.path.join(base, f"FLOW#{num}.mp4"),
                os.path.join(base, f"flow#{num}.mp4"),
                os.path.join(base, f"flow{num}.mp4"),
            ])
    for ruta in candidatos:
        if os.path.isfile(ruta) and os.path.getsize(ruta) > 1000:
            return ruta
    return None


def extraer_clips_flow_del_material(texto):
    """Extrae las escenas marcadas con FLOW #N del guion o material."""
    if not texto:
        return []
    
    indices = []
    # Patron 1: [0:00] Titulo — FLOW #1
    bloques_flow = re.finditer(
        r'(?:\[(?P<tiempo>\d+:\d+)\]\s*)?(?P<titulo>[^\n—\-]+?)\s*[-—]\s*(?:\[)?FLOW\s*#?(?P<num>\d+)(?:\])?',
        texto, re.IGNORECASE
    )
    for m in bloques_flow:
        indices.append({
            "inicio": m.start(),
            "num": int(m.group("num")),
            "titulo": m.group("titulo").strip(),
            "tiempo": m.group("tiempo") or "",
        })
    
    # Patron 2 de respaldo: FLOW #N
    if not indices:
        for m in re.finditer(r'FLOW\s*#?(?P<num>\d+)', texto, re.IGNORECASE):
            indices.append({
                "inicio": m.start(),
                "num": int(m.group("num")),
                "titulo": f"FLOW #{m.group('num')}",
                "tiempo": "",
            })
    
    indices.sort(key=lambda x: x["inicio"])
    clips = []
    for i, item in enumerate(indices):
        fin_trozo = indices[i + 1]["inicio"] if i + 1 < len(indices) else len(texto)
        trozo = texto[item["inicio"]:fin_trozo]
        
        audio = ""
        m_audio = re.search(r'Audio\s*/\s*Voz\s*en\s*off(?:\s*\([^)]*\))?:\s*(.*?)(?=\n\s*(?:Visuales|Using|\[)|$)',
                            trozo, re.DOTALL | re.IGNORECASE)
        if m_audio:
            audio = " ".join(m_audio.group(1).split()).strip()
            
        prompt = ""
        m_prompt = re.search(r'(Using\s+the\s+reference\s+image.*?(?:\d+\s*seconds|\d+\s*s\b|\.))',
                             trozo, re.DOTALL | re.IGNORECASE)
        if m_prompt:
            prompt = " ".join(m_prompt.group(1).split()).strip()
        else:
            m_alt = re.search(r'((?:flat\s+2d|vector|camera|dark|robot).*?\d+\s*seconds)',
                              trozo, re.DOTALL | re.IGNORECASE)
            if m_alt:
                prompt = " ".join(m_alt.group(1).split()).strip()
                
        cuarta_pared = bool(re.search(r'CUARTA\s*PARED', item["titulo"] + " " + trozo[:200], re.IGNORECASE))
        
        clips.append({
            "num": item["num"],
            "titulo": item["titulo"],
            "tiempo": item["tiempo"],
            "prompt": prompt,
            "audio": audio,
            "cuarta_pared": cuarta_pared,
        })
        
    vistos = {}
    for c in clips:
        n = c["num"]
        if n not in vistos or len(c.get("prompt", "")) > len(vistos[n].get("prompt", "")):
            vistos[n] = c
    return sorted(vistos.values(), key=lambda x: x["num"])


def _palabras_clave(texto):
    if not texto:
        return set()
    limpio = re.sub(r'[^\w\s]', '', texto.lower())
    return {p for p in limpio.split() if len(p) > 3}


def emparejar_escenas_con_flow(escenas, clips_flow):
    """Empareja las escenas de plan.json con los clips de Flow por similitud de texto.
    
    ESTRICTAMENTE 1 A 1: cada clip de vídeo de Flow (8 segundos) corresponde a
    UNA SOLA ESCENA del montaje, nunca a múltiples escenas continuas.
    """
    if not escenas or not clips_flow:
        return escenas

    escenas_por_id = {e.get("id"): e for e in escenas if e.get("id")}
    asignadas = set()

    for clip in clips_flow:
        c_num = clip.get("num")
        objetivo_id = clip.get("escena_id")
        
        mejor_escena = None
        # A. Si el clip ya apunta a un ID válido y no está ocupado
        if objetivo_id and objetivo_id in escenas_por_id and objetivo_id not in asignadas:
            mejor_escena = escenas_por_id[objetivo_id]
        else:
            # B. Buscar la escena única que mejor coincida con el audio del clip
            pal_audio = _palabras_clave(clip.get("audio", ""))
            mejor_solape = 0
            if pal_audio:
                for escena in escenas:
                    sid = escena.get("id")
                    if sid in asignadas:
                        continue
                    narr = escena.get("narracion", "")
                    pal_escena = _palabras_clave(narr)
                    if not pal_escena:
                        continue
                    solape = len(pal_escena & pal_audio)
                    if solape >= 4 and solape > mejor_solape:
                        mejor_solape = solape
                        mejor_escena = escena
        
        if mejor_escena:
            sid = mejor_escena.get("id")
            asignadas.add(sid)
            mejor_escena["flow_num"] = c_num
            mejor_escena["tipo_visual"] = "flow_video"
            mejor_escena["video_manual"] = True
            if clip.get("prompt"):
                mejor_escena["flow_prompt"] = clip["prompt"]
            if clip.get("cuarta_pared"):
                mejor_escena["cuarta_pared"] = True
            clip["escena_id"] = sid

    # Limpiar marcas en escenas no asignadas a un clip único
    for escena in escenas:
        if escena.get("id") not in asignadas:
            if "flow_num" in escena:
                escena.pop("flow_num", None)
            if escena.get("tipo_visual") == "flow_video":
                escena.pop("tipo_visual", None)
            if "flow_prompt" in escena:
                escena.pop("flow_prompt", None)
            if "video_manual" in escena:
                escena.pop("video_manual", None)

    return escenas


def exportar_prompts_video(ruta_proyecto, material_texto=None, escenas=None):
    """Genera prompts_video.txt y videos.json en flow/."""
    dir_flow = carpeta_flow(ruta_proyecto)
    dir_vid = carpeta_videos(ruta_proyecto)
    os.makedirs(dir_flow, exist_ok=True)
    os.makedirs(dir_vid, exist_ok=True)
    
    if not material_texto:
        rutas_posibles = [
            os.path.join(ruta_proyecto, "pasos", "ingesta", "material.txt"),
            os.path.join(ruta_proyecto, "ingesta.txt"),
            os.path.join(ruta_proyecto, "guion.txt")
        ]
        for r in rutas_posibles:
            if os.path.isfile(r):
                try:
                    with open(r, encoding="utf-8") as fh:
                        material_texto = fh.read()
                        break
                except Exception:
                    pass
                    
    clips = extraer_clips_flow_del_material(material_texto)
    if escenas and clips:
        emparejar_escenas_con_flow(escenas, clips)
        
    lineas = [
        "================================================================================",
        "CLIPS ANIMADOS DE GOOGLE FLOW (8 SEGUNDOS)",
        "================================================================================",
        "Instrucciones:",
        "1. Genera cada clip en Google Flow usando su prompt en inglés (duración: 8 s).",
        "2. Guarda el vídeo descargado en la carpeta:",
        f"   proyectos/{os.path.basename(os.path.normpath(ruta_proyecto))}/flow/videos/",
        "   con el nombre flow_<N>.mp4 (ej: flow_1.mp4) o con el ID del plano (ej: S001.mp4).",
        "3. El render del Estudio detectará el archivo y lo integrará automáticamente.",
        "================================================================================\n"
    ]
    
    mapa_escenas = {}
    if escenas:
        for e in escenas:
            fnum = e.get("flow_num")
            if fnum:
                mapa_escenas[fnum] = e
                
    fichas_json = []
    for c in clips:
        num = c["num"]
        escena = mapa_escenas.get(num)
        sid = escena.get("id") if escena else ""
        dur_voz = f"{escena.get('duracion', 0):.1f}s" if escena else "según voz"
        
        archivo_video = buscar_video_de_escena(ruta_proyecto, sid or f"S{num:03d}", flow_num=num)
        estado_txt = "LISTO (archivo presente)" if archivo_video else "PENDIENTE (falta generar)"
        
        lineas.append(f"--- FLOW #{num}: {c['titulo']} ---")
        lineas.append(f"Estado: {estado_txt}")
        if sid:
            lineas.append(f"Plano asignado: {sid} (Duración de locución: {dur_voz})")
        if c.get("cuarta_pared"):
            lineas.append("Efecto: [CUARTA PARED] - Scratch de cinta y corte seco de música")
        lineas.append("Prompt en inglés para Flow:")
        lineas.append(c["prompt"] or "(sin prompt específico extraído)")
        lineas.append(f"Nombre de archivo recomendado: flow_{num}.mp4" + (f" o {sid}.mp4\n" if sid else "\n"))
        
        fichas_json.append({
            "num": num,
            "titulo": c["titulo"],
            "prompt": c["prompt"],
            "escena_id": sid,
            "cuarta_pared": c.get("cuarta_pared", False),
            "duracion_voz": escena.get("duracion") if escena else None,
            "archivo_recomendado": f"flow_{num}.mp4",
            "presente": bool(archivo_video),
            "ruta": os.path.relpath(archivo_video, ruta_proyecto) if archivo_video else None
        })
        
    ruta_txt = os.path.join(dir_flow, "prompts_video.txt")
    with open(ruta_txt, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas))
        
    ruta_json = os.path.join(dir_flow, "videos.json")
    with open(ruta_json, "w", encoding="utf-8") as fh:
        json.dump({"total": len(fichas_json), "clips": fichas_json}, fh, ensure_ascii=False, indent=2)
        
    return {"total": len(fichas_json), "clips": fichas_json, "ruta_txt": ruta_txt}


def estado_videos(ruta_proyecto, clips_flow=None):
    """Resumen del estado de los clips de video en flow/videos/."""
    dir_vid = carpeta_videos(ruta_proyecto)
    if not os.path.isdir(dir_vid):
        return {"total": 0, "listos": 0, "faltan": 0, "archivos": []}
    ficheros = [f for f in os.listdir(dir_vid) if f.lower().endswith(".mp4")]
    total = len(clips_flow) if clips_flow else len(ficheros)
    return {"total": total, "listos": len(ficheros), "archivos": ficheros}


def generar_prompt_video_escena(escena, estilo=None):
    """Genera un prompt cinematográfico en inglés para Google Flow Video (8 s)."""
    sid = escena.get("id") or "escena"
    narracion = (escena.get("narracion") or "").strip()
    duracion = float(escena.get("duracion") or 0.0)
    prompt_base = (escena.get("prompt") or "").strip()
    accion = (escena.get("accion") or escena.get("direccion") or "").strip()

    # Intentar generar con Claude si está disponible
    prompt_ia = None
    try:
        instruccion = (
            "You are a cinematic director creating motion prompts for Google Flow / Veo (8-second video clips). "
            "Write a concise English prompt to generate a short animated video clip for this specific scene.\n\n"
            f"Scene ID: {sid}\n"
            f"Voiceover line in Spanish: \"{narracion}\"\n"
            f"Duration of voiceover: {duracion:.1f} seconds\n"
            f"Visual description/action: {accion or prompt_base}\n\n"
            "Requirements for the prompt:\n"
            "1. Must start with: \"Using the reference image for character and art style: \"\n"
            "2. Describe the motion, camera action, and animation smoothly matching the narration.\n"
            "3. State the style: \"flat 2D vector style, clean composition, subtle cinematic motion.\"\n"
            "4. End with: \"No text, no letters, no logos, no watermark. 8 seconds.\"\n"
            "5. Return ONLY the English prompt in one paragraph, no quotes, no conversational filler."
        )
        texto, _ = cli_claude.ejecutar(instruccion, modelo="haiku", esfuerzo="low",
                                       para=f"prompt de video Flow para {sid}")
        if texto and len(texto.strip()) > 30:
            prompt_ia = " ".join(texto.split()).strip().strip('"')
    except Exception:
        prompt_ia = None

    if prompt_ia and "using the reference image" in prompt_ia.lower():
        return prompt_ia

    # Plantilla de respaldo algorítmica si no hay sesión de Claude activa
    descripcion = accion if accion else narracion
    base_limpia = prompt_base.replace(REMITE, "") if prompt_base else ""
    if len(base_limpia) > 200:
        base_limpia = base_limpia[:197] + "..."

    accion_en = f"animated scene depicting: {descripcion}" if descripcion else "subtle animated movement"
    prompt_fallback = (
        f"Using the reference image for character and art style: {base_limpia or accion_en}. "
        "Flat 2D vector style, subtle cinematic camera movement, smooth animation. "
        "No text, no letters, no logos, no watermark. 8 seconds."
    )
    return prompt_fallback

