"""
Motor de imagen sobre Google Vertex AI: Gemini con imagen («Nano Banana»).

Hace lo mismo que motores/imagen_openai/imagen.py y devuelve LO MISMO --
`generar(prompt, referencias, quality=, tamano=) -> (png, meta)` -- para que el
paso de assets no se entere de quien dibuja. Es el mismo modelo que hay detras
de Google Flow, asi que el estilo que ya se ha visto en Flow se mantiene; la
diferencia es que aqui se adjuntan las referencias solas (estilo, reparto,
continuidad) y no hay que hacer nada a mano.

Se llama `vertex.py` y no `imagen.py` A PROPOSITO: el medidor de coste
(nucleo/coste.py) engancha cualquier `imagen.py` que se cargue como si fuera el
de OpenAI y le calcularia el precio con la tarifa de OpenAI. Este tiene su
propio enganche (`_medir_imagen_vertex`).

Tres cosas que explican el codigo
---------------------------------
1. AUTENTICACION SIN LIBRERIAS. Vertex no acepta una clave de API normal: pide
   un token OAuth que se obtiene firmando un JWT con la clave privada de una
   CUENTA DE SERVICIO (el .json que se descarga en la consola). Firmar RS256 son
   cuatro lineas de aritmetica con `pow`, asi que se hace aqui y no se instala
   google-auth. El token dura una hora y se reutiliza.
2. COMO MUCHO TRES IMAGENES DE ENTRADA. gemini-2.5-flash-image admite tres por
   peticion y un plano del Estudio lleva a menudo mas (la lamina de estilo, las
   hojas de reparto, los dos planos anteriores). El prompt las cita por numero
   («Reference image 5 is ...»), asi que no se puede tirar ninguna sin que el
   prompt mienta. Con mas de tres, la 1 --la de estilo, que es la que manda-- va
   sola y el resto se empaqueta en HOJAS DE CONTACTO con cada viñeta numerada,
   y el prompt lo dice delante.
3. EL TAMANO. Se pide la proporcion (3:2, 2:3, 1:1) y lo que vuelve se lleva
   al tamano exacto con el que trabaja el Estudio (1536x1024...).

Configuracion (por contrato, sin importar nada del Estudio)
-----------------------------------------------------------
    secretos/vertex_cuenta.json   la clave de la cuenta de servicio, tal cual
    secretos/vertex.json          {"modelo", "ubicacion", "proyecto"} (opcional:
                                  el proyecto sale de la cuenta de servicio)
"""
import base64
import hashlib
import io
import json
import math
import os
import threading
import time

import requests
from PIL import Image, ImageDraw, ImageFont

MODELO_POR_DEFECTO = "gemini-2.5-flash-image"
UBICACION_POR_DEFECTO = "global"
TAMANOS = {"apaisado": (1536, 1024), "cuadrado": (1024, 1024), "vertical": (1024, 1536)}
PROPORCION = {"apaisado": "3:2", "cuadrado": "1:1", "vertical": "2:3"}

#: Tarifa de gemini-2.5-flash-image en Vertex, en dolares por millon de tokens.
#: Una imagen de salida son ~1.290 tokens (~0,039 $). Si Google la cambia, se
#: cambia aqui: es el unico sitio de donde sale el importe.
USD_ENTRADA_MTOK = 0.30
USD_SALIDA_MTOK = 30.0
TOKENS_POR_IMAGEN = 1290

#: Imagenes de entrada que admite el modelo por peticion.
MAX_ENTRADAS = 3

#: Llamadas a la vez. La prueba gratuita de Google Cloud no deja pedir mas
#: cuota, asi que ir de dos en dos evita comerse el limite por minuto.
CONCURRENCIA = 2
_TURNOS = threading.Semaphore(CONCURRENCIA)

SCOPE = "https://www.googleapis.com/auth/cloud-platform"

CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")


def _secretos():
    return os.environ.get("ESTUDIO_SECRETOS") or CARPETA_SECRETOS


def ruta_config():
    return os.path.join(_secretos(), "vertex.json")


def ruta_cuenta():
    return os.path.join(_secretos(), "vertex_cuenta.json")


def _leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def cuenta_de_servicio():
    """La clave de la cuenta de servicio, o {} si no hay."""
    return _leer(ruta_cuenta())


def configuracion():
    """Modelo, ubicacion y proyecto, con los que faltan puestos."""
    datos = _leer(ruta_config())
    cuenta = cuenta_de_servicio()
    return {
        "modelo": str(datos.get("modelo") or MODELO_POR_DEFECTO),
        "ubicacion": str(datos.get("ubicacion") or UBICACION_POR_DEFECTO),
        "proyecto": str(datos.get("proyecto") or cuenta.get("project_id") or ""),
    }


def listo():
    """Si hay con que hablar con Vertex: una cuenta de servicio con su clave."""
    cuenta = cuenta_de_servicio()
    return bool(cuenta.get("private_key") and cuenta.get("client_email")
                and configuracion()["proyecto"])


# ------------------------------------------------------------------ el token
#
# RS256 A MANO. Una clave RSA en PKCS#8 es un arbol DER; de ahi se sacan n, d,
# p, q y los exponentes de CRT, y firmar es EMSA-PKCS1-v1_5: rellenar el hash
# con su prefijo DigestInfo y elevarlo a d modulo n.

_PREFIJO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def _der(datos, pos=0):
    """Un TLV de DER. -> (etiqueta, contenido, siguiente)"""
    etiqueta = datos[pos]
    largo = datos[pos + 1]
    pos += 2
    if largo & 0x80:
        n = largo & 0x7F
        largo = int.from_bytes(datos[pos:pos + n], "big")
        pos += n
    return etiqueta, datos[pos:pos + largo], pos + largo


def _secuencia(contenido):
    """Los elementos de una SEQUENCE DER. -> [(etiqueta, contenido)]"""
    elementos, pos = [], 0
    while pos < len(contenido):
        etiqueta, valor, pos = _der(contenido, pos)
        elementos.append((etiqueta, valor))
    return elementos


def _clave_rsa(pem):
    """n, e, d, p, q, dp, dq, qinv de una clave privada PEM (PKCS#8 o PKCS#1)."""
    cuerpo = "".join(l for l in pem.strip().splitlines()
                     if l and not l.startswith("-----"))
    der = base64.b64decode(cuerpo)
    _, contenido, _ = _der(der)
    elementos = _secuencia(contenido)
    if len(elementos) >= 3 and elementos[1][0] == 0x30:     # PKCS#8
        _, interior, _ = _der(elementos[2][1])
        elementos = _secuencia(interior)
    enteros = [int.from_bytes(v, "big") for t, v in elementos if t == 0x02]
    # version, n, e, d, p, q, dp, dq, qinv
    return enteros[1:9]


def firmar_rs256(mensaje, pem):
    """Firma RS256 (PKCS#1 v1.5 + SHA-256). -> bytes"""
    n, _e, d, p, q, dp, dq, qinv = _clave_rsa(pem)
    k = (n.bit_length() + 7) // 8
    t = _PREFIJO_SHA256 + hashlib.sha256(mensaje).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    m = int.from_bytes(em, "big")
    # CRT: lo mismo que pow(m, d, n) y cuatro veces mas rapido
    m1, m2 = pow(m, dp, p), pow(m, dq, q)
    h = (qinv * (m1 - m2)) % p
    return (m2 + h * q).to_bytes(k, "big")


def _b64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=")


_TOKEN = {"valor": "", "caduca": 0.0, "cuenta": ""}
_TOKEN_LOCK = threading.Lock()


def token():
    """Un token OAuth de la cuenta de servicio, reutilizado mientras valga."""
    cuenta = cuenta_de_servicio()
    if not (cuenta.get("private_key") and cuenta.get("client_email")):
        raise RuntimeError(
            "falta la clave de la cuenta de servicio de Google Cloud: súbela en "
            "Configuración > Imágenes > Google Vertex")
    with _TOKEN_LOCK:
        if (_TOKEN["valor"] and _TOKEN["cuenta"] == cuenta["client_email"]
                and time.time() < _TOKEN["caduca"] - 120):
            return _TOKEN["valor"]
        ahora = int(time.time())
        destino = cuenta.get("token_uri") or "https://oauth2.googleapis.com/token"
        cabecera = {"alg": "RS256", "typ": "JWT"}
        if cuenta.get("private_key_id"):
            cabecera["kid"] = cuenta["private_key_id"]
        reclamos = {"iss": cuenta["client_email"], "scope": SCOPE, "aud": destino,
                    "iat": ahora, "exp": ahora + 3600}
        sin_firma = (_b64url(json.dumps(cabecera, separators=(",", ":")).encode())
                     + b"." + _b64url(json.dumps(reclamos, separators=(",", ":")).encode()))
        jwt = sin_firma + b"." + _b64url(firmar_rs256(sin_firma, cuenta["private_key"]))
        r = requests.post(destino, timeout=30, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt.decode("ascii")})
        if r.status_code != 200:
            raise RuntimeError(f"Google no acepta la cuenta de servicio "
                               f"(HTTP {r.status_code}): {r.text[:300]}")
        datos = r.json()
        _TOKEN.update(valor=datos["access_token"],
                      caduca=time.time() + float(datos.get("expires_in") or 3600),
                      cuenta=cuenta["client_email"])
        return _TOKEN["valor"]


# ------------------------------------------------------------ las referencias

def _png_b64(ruta_o_imagen, lado_max=1024):
    img = (ruta_o_imagen if isinstance(ruta_o_imagen, Image.Image)
           else Image.open(ruta_o_imagen))
    img = img.convert("RGB")
    if max(img.size) > lado_max:
        escala = lado_max / max(img.size)
        img = img.resize((max(1, round(img.width * escala)),
                          max(1, round(img.height * escala))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _fuente(tamano):
    try:
        return ImageFont.load_default(size=tamano)
    except TypeError:                                # Pillow < 10.1
        return ImageFont.load_default()


def hoja_de_contacto(rutas, numeros, lado=1536):
    """Varias referencias en una imagen, cada viñeta con su numero. -> Image"""
    cuantas = len(rutas)
    columnas = 1 if cuantas == 1 else 2
    filas = math.ceil(cuantas / columnas)
    celda = lado // columnas
    alto_celda = round(celda * 2 / 3)
    hoja = Image.new("RGB", (celda * columnas, alto_celda * filas), "white")
    pincel = ImageDraw.Draw(hoja)
    letra = _fuente(max(24, celda // 12))
    for i, (ruta, numero) in enumerate(zip(rutas, numeros)):
        img = Image.open(ruta).convert("RGB")
        img.thumbnail((celda - 8, alto_celda - 8), Image.LANCZOS)
        x = (i % columnas) * celda + (celda - img.width) // 2
        y = (i // columnas) * alto_celda + (alto_celda - img.height) // 2
        hoja.paste(img, (x, y))
        etiqueta = str(numero)
        caja = pincel.textbbox((0, 0), etiqueta, font=letra)
        ancho, alto = caja[2] - caja[0] + 16, caja[3] - caja[1] + 12
        x0, y0 = (i % columnas) * celda + 6, (i // columnas) * alto_celda + 6
        pincel.rectangle((x0, y0, x0 + ancho, y0 + alto), fill="black")
        pincel.text((x0 + 8, y0 + 4 - caja[1]), etiqueta, fill="white", font=letra)
    return hoja


def empaquetar(referencias):
    """Las referencias en como mucho MAX_ENTRADAS imagenes. -> (partes, aviso)

    `partes` son los base64 que se adjuntan, en orden; `aviso` es lo que va
    delante del prompt para que «Reference image N» siga siendo la N.
    """
    if len(referencias) <= MAX_ENTRADAS:
        return [_png_b64(r) for r in referencias], ""
    resto = list(enumerate(referencias, start=1))[1:]
    huecos = MAX_ENTRADAS - 1
    por_hoja = math.ceil(len(resto) / huecos)
    partes, descripcion = [_png_b64(referencias[0])], ["attached image 1 is reference image 1"]
    for h in range(huecos):
        trozo = resto[h * por_hoja:(h + 1) * por_hoja]
        if not trozo:
            continue
        numeros = [n for n, _ in trozo]
        partes.append(_png_b64(hoja_de_contacto([r for _, r in trozo], numeros),
                               lado_max=1536))
        descripcion.append(
            f"attached image {len(partes)} is a contact sheet holding reference "
            f"images {', '.join(str(n) for n in numeros)} (each panel is labeled "
            f"with its number in the top-left corner)")
    aviso = ("REFERENCE LAYOUT: " + "; ".join(descripcion) + ". Wherever the "
             "text below says «Reference image N», it means the panel or image "
             "labeled N. The labels are only for you: never draw numbers, "
             "labels or panel borders in the output.\n\n")
    return partes, aviso


# ------------------------------------------------------------------ generar

def _url(cfg):
    ubicacion = cfg["ubicacion"]
    host = ("aiplatform.googleapis.com" if ubicacion == "global"
            else f"{ubicacion}-aiplatform.googleapis.com")
    return (f"https://{host}/v1/projects/{cfg['proyecto']}/locations/{ubicacion}"
            f"/publishers/google/models/{cfg['modelo']}")


def coste_de(uso):
    """Dolares de una llamada a partir de su usageMetadata."""
    uso = uso or {}
    entrada = int(uso.get("promptTokenCount") or 0)
    salida = int(uso.get("candidatesTokenCount") or 0) or TOKENS_POR_IMAGEN
    return round(entrada * USD_ENTRADA_MTOK / 1e6 + salida * USD_SALIDA_MTOK / 1e6, 5)


def _encajar(png, tamano):
    """La imagen devuelta, recortada al centro y llevada al tamano del Estudio."""
    ancho, alto = TAMANOS.get(tamano, TAMANOS["apaisado"])
    img = Image.open(io.BytesIO(png)).convert("RGB")
    objetivo = ancho / alto
    if abs(img.width / img.height - objetivo) > 0.01:
        if img.width / img.height > objetivo:
            nuevo = round(img.height * objetivo)
            izq = (img.width - nuevo) // 2
            img = img.crop((izq, 0, izq + nuevo, img.height))
        else:
            nuevo = round(img.width / objetivo)
            arriba = (img.height - nuevo) // 2
            img = img.crop((0, arriba, img.width, arriba + nuevo))
    if img.size != (ancho, alto):
        img = img.resize((ancho, alto), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _bloqueo(datos):
    """Por que no ha vuelto imagen, si lo dice. -> texto o ''"""
    feedback = datos.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        return f"el prompt se ha bloqueado ({feedback['blockReason']})"
    for candidato in datos.get("candidates") or []:
        razon = candidato.get("finishReason")
        if razon and razon not in ("STOP", "MAX_TOKENS"):
            return f"la imagen se ha bloqueado ({razon})"
    return ""


def generar(prompt, referencias, *, quality="low", tamano="apaisado",
            reintentos=5, avisar=None):
    """Una imagen. -> (png, meta) con la misma forma que el motor de OpenAI.

    `quality` no existe en Gemini: se acepta y se ignora, para que quien llama
    no tenga que saber con que motor habla.
    """
    faltan = [r for r in (referencias or []) if not os.path.exists(r)]
    if faltan:
        raise ValueError("estas imagenes de referencia no existen: "
                         + ", ".join(str(f) for f in faltan[:5]))
    cfg = configuracion()
    if not cfg["proyecto"]:
        raise RuntimeError("falta el proyecto de Google Cloud: sube la clave de "
                           "la cuenta de servicio en Configuración")
    partes_img, aviso = empaquetar(list(referencias or []))
    partes = [{"inlineData": {"mimeType": "image/png", "data": b64}}
              for b64 in partes_img]
    partes.append({"text": aviso + prompt})
    cuerpo = {
        "contents": [{"role": "user", "parts": partes}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": PROPORCION.get(tamano, "3:2")},
        },
    }
    url = _url(cfg) + ":generateContent"
    ultimo, bloqueos = "", 0
    for intento in range(reintentos + 1):
        with _TURNOS:
            t0 = time.time()
            try:
                r = requests.post(url, json=cuerpo, timeout=300,
                                  headers={"Authorization": f"Bearer {token()}"})
            except requests.RequestException as fallo:
                ultimo = f"sin red: {fallo}"
                time.sleep(min(5 * (intento + 1), 30))
                continue
            segundos = time.time() - t0
        if r.status_code == 200:
            datos = r.json()
            for candidato in datos.get("candidates") or []:
                for parte in (candidato.get("content") or {}).get("parts") or []:
                    dato = (parte.get("inlineData") or {}).get("data")
                    if dato:
                        uso = datos.get("usageMetadata") or {}
                        return _encajar(base64.b64decode(dato), tamano), {
                            "segundos": round(segundos, 1), "quality": quality,
                            "refs": len(referencias or []), "coste": coste_de(uso),
                            "modelo": cfg["modelo"], "tamano": tamano,
                            "usage": uso, "proveedor": "vertex"}
            # SIN IMAGEN: casi siempre un filtro de seguridad. A veces es
            # aleatorio y a la segunda sale; mas de un reintento es insistir
            # contra un filtro que no va a cambiar de opinion.
            ultimo = _bloqueo(datos) or "Google ha contestado sin imagen"
            bloqueos += 1
            if bloqueos <= 1 and intento < reintentos:
                continue
            raise RuntimeError(
                f"{ultimo}: los filtros de Google no han dejado dibujar este "
                f"plano. Suele pasar con personas reales o famosas; cambia la "
                f"nota o el prompt del plano y vuelve a generarlo")
        ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
        if r.status_code in (401, 403):
            raise RuntimeError(
                "Google no deja usar Vertex con esta cuenta de servicio: "
                "comprueba que la API de Vertex AI está activada en el proyecto "
                f"y que la cuenta tiene el permiso «Vertex AI User». {ultimo}")
        if r.status_code == 404:
            raise RuntimeError(f"el modelo {cfg['modelo']} no está en "
                               f"{cfg['ubicacion']} para este proyecto. {ultimo}")
        if r.status_code == 429 and intento < reintentos:
            # la cuota de la prueba gratuita no se puede subir: se espera
            espera = min(15 * (2 ** intento), 120)
            for s_restante in range(espera, 0, -1):
                if callable(avisar):
                    try:
                        avisar(None, f"cuota_429:{s_restante}:{espera}:{intento + 1}:{reintentos}")
                    except Exception:
                        pass
                time.sleep(1)
            continue
        if r.status_code >= 500 and intento < reintentos:
            time.sleep(min(5 * (intento + 1), 30))
            continue
        break
    raise RuntimeError(f"Vertex no ha podido generar la imagen: {ultimo}")


def normalizar(ruta, cache_dir, lado_max=1024):
    """La MISMA normalizacion que el motor de OpenAI (PNG, tamano, cache).

    Quien prepara las referencias (p6_assets, moodboard) llama a `normalizar`
    del motor que tiene delante; hacerla dos veces distinta daria cache
    distinta para la misma lamina. Se carga el otro motor por ruta, sin
    importar nada del Estudio.
    """
    import importlib.util                                    # noqa: PLC0415
    ruta_openai = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "imagen_openai", "imagen.py")
    if "_normalizador" not in _NORMALIZADOR:
        spec = importlib.util.spec_from_file_location("_imagen_openai_norm", ruta_openai)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        _NORMALIZADOR["_normalizador"] = modulo.normalizar
    return _NORMALIZADOR["_normalizador"](ruta, cache_dir, lado_max=lado_max)


_NORMALIZADOR = {}


def probar():
    """Comprueba la cuenta, el proyecto y el modelo SIN generar nada.

    countTokens no se cobra: si contesta, el token vale, la API esta activada y
    el modelo existe en esa ubicacion. -> {estado, mensaje}
    """
    if not cuenta_de_servicio():
        return {"estado": "sin_clave", "mensaje": "no hay cuenta de servicio puesta"}
    try:
        cfg = configuracion()
        r = requests.post(_url(cfg) + ":countTokens", timeout=30,
                          headers={"Authorization": f"Bearer {token()}"},
                          json={"contents": [{"role": "user",
                                              "parts": [{"text": "hola"}]}]})
    except requests.RequestException as fallo:
        return {"estado": "sin_red", "mensaje": f"no se ha podido hablar con Google: {fallo}"}
    except RuntimeError as fallo:
        return {"estado": "mal", "mensaje": str(fallo)}
    if r.status_code == 200:
        return {"estado": "ok",
                "mensaje": f"la cuenta autentica y {cfg['modelo']} contesta en "
                           f"el proyecto {cfg['proyecto']} ({cfg['ubicacion']})"}
    return {"estado": "mal", "mensaje": f"Google contesta {r.status_code}: {r.text[:300]}"}
