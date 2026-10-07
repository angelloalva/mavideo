"""Los prompts de cada plano, listos para pegar en Google Flow a mano.

Para quien no genera las imagenes con OpenAI sino a mano en Flow y luego las
adopta (`motor_imagen: "adoptar"` en el paso de assets). Escribe, dentro del
proyecto, en `flow/`:

  * `prompts.txt`  -- un bloque por plano que necesita imagen: su id, la frase
    que se narra y el prompt, con la FRASE DE ESTILO delante;
  * `estilo.txt`   -- esa frase, para que todo el video use la misma aunque se
    vuelva a exportar;
  * `planos.json`  -- los ids en orden, que es lo que lee `flow_renombrar.py`.

    python herramientas/flow_prompts.py <proyecto> --preparar   # una vez
    python herramientas/flow_prompts.py <proyecto>
    python herramientas/flow_prompts.py <proyecto> --sugerir    # otra frase
    python herramientas/flow_prompts.py <proyecto> --estilo "Flat 2D ..."

LA FRASE DE ESTILO. Los prompts del Estudio dicen QUE se ve en cada plano; COMO
se dibuja lo ponen normalmente las imagenes de referencia que se adjuntan a
OpenAI. En Flow no hay adjuntos, asi que sin una frase fija cada imagen saldria
en un estilo. La primera vez se le pide al CLI de Claude (sonnet, esfuerzo
bajo: una llamada corta a la cuota del plan, sin coste por uso) que proponga
paleta y ambiente segun el guion, sobre una base fija de ilustracion plana. Se
guarda y NO se vuelve a pedir salvo con --sugerir: cambiarla a mitad de video es
justo la incoherencia que existe para evitar.

--preparar escribe en el paso de assets los params que este flujo necesita:
el motor 'adoptar' y la carpeta `flow/imagenes` como arte previo. El corte en
planos NO: lo decide el deslizador de ritmo (Muy lento = planos de 6-9 s).
Con «Imagenes: Google Flow» en Configuracion, los videos nuevos ya nacen asi y
la pantalla hace todo esto sola; el script queda para los proyectos de antes. Va por la API del Estudio,
que tiene que estar arrancado: escribir `estado.json` por detras de un servidor
que lo tiene abierto es pedir que uno pise al otro. Solo se escribe lo que
cambia, y hay que pedirlo: la regla 1 del CLAUDE.md.

EL PLAN TIENE QUE SER EL MISMO QUE EL DEL PASO. Los ids son posicionales: si
despues de exportar cambian el guion, la voz o el corte, S014 pasa a narrar
otra cosa. Por eso el plan se calcula con los params GUARDADOS del paso (los
mismos que usara al ejecutarse), y si se toca algo de eso despues hay que
volver a exportar antes de descargar mas. `planos.json` guarda la narracion de
cada id, y el renombrador la ensena al lado de cada fichero.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from nucleo.proyecto import Proyecto            # noqa: E402
from nucleo.estado import Estado                # noqa: E402
from pasos import flow                          # noqa: E402

API = os.environ.get("ESTUDIO_URL", "http://127.0.0.1:8020").rstrip("/")

# La logica vive en pasos/flow.py, que es lo mismo que usa la pantalla. Estos
# nombres se quedan aqui porque flow_renombrar.py los importa de este fichero.
BASE_ESTILO = flow.BASE_ESTILO
carpeta_flow = flow.carpeta_flow


def carpeta_proyecto(nombre):
    """Acepta la ruta de la carpeta o el id de un proyecto de `proyectos/`."""
    if os.path.isdir(nombre):
        return os.path.abspath(nombre)
    raiz = os.environ.get("ESTUDIO_PROYECTOS") or os.path.join(RAIZ, "proyectos")
    ruta = os.path.join(raiz, nombre)
    if not os.path.isdir(ruta):
        raise SystemExit(f"no encuentro el proyecto '{nombre}' (ni como carpeta "
                         f"ni dentro de {raiz})")
    return ruta


def _api(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(API + ruta, method=metodo, data=datos,
                                      headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return json.load(respuesta)


def preparar(pid, ruta_proyecto):
    """Escribe por la API los params del flujo de Flow que aun no esten."""
    try:
        actuales = _api("GET", f"/api/proyectos/{pid}/pasos/assets")["params"]
    except (urllib.error.URLError, OSError) as fallo:
        raise SystemExit(f"--preparar necesita el Estudio arrancado en {API} "
                         f"({fallo}). Arrancalo con: python app.py --puerto 8020")
    os.makedirs(flow.carpeta_imagenes(ruta_proyecto), exist_ok=True)
    deseados = flow.params_flow(ruta_proyecto)
    cambios = {k: v for k, v in deseados.items() if actuales.get(k) != v}
    if not cambios:
        print("el paso de assets ya estaba preparado para Flow")
        return
    _api("PUT", f"/api/proyectos/{pid}/pasos/assets/params", {"params": cambios})
    for clave, valor in cambios.items():
        print(f"  assets.{clave} = {valor}")


def exportar(ruta_proyecto, estilo_fijado=None, sugerir=False, sin_claude=False):
    proyecto = Proyecto(ruta_proyecto)
    params = Estado(proyecto).params("assets")
    if not flow.es_flow(params):
        print("AVISO: el paso de assets no esta en modo 'adoptar'; si lo "
              "ejecutas asi generara con OpenAI y COBRARA. Corre antes con "
              "--preparar.")
    try:
        hecho = flow.exportar(proyecto, params, estilo_fijado, sugerir,
                              sin_claude, avisar=print)
    except RuntimeError as fallo:
        raise SystemExit(str(fallo))
    return hecho["planos"], hecho["estilo"], hecho["dir_flow"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("proyecto", help="id del proyecto o ruta de su carpeta")
    ap.add_argument("--preparar", action="store_true",
                    help="dejar el paso de assets en modo adoptar (el ritmo lo pone la pantalla)")
    ap.add_argument("--estilo", help="fijar la frase de estilo a mano")
    ap.add_argument("--sugerir", action="store_true",
                    help="pedir a Claude otra frase aunque ya haya una guardada")
    ap.add_argument("--sin-claude", action="store_true",
                    help="no llamar al CLI: usar solo la base fija")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ruta = carpeta_proyecto(args.proyecto)
    if args.preparar:
        preparar(os.path.basename(ruta), ruta)
    planos, estilo, dir_flow = exportar(ruta, args.estilo, args.sugerir,
                                        args.sin_claude)
    print(f"\nestilo: {estilo}\n")
    print(f"{len(planos)} prompts en {os.path.join(dir_flow, 'prompts.txt')}")
    print(f"las imagenes de Flow van a {os.path.join(dir_flow, 'imagenes')} "
          f"(con herramientas/flow_renombrar.py)")


if __name__ == "__main__":
    main()
