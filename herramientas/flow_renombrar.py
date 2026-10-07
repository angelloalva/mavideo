"""Las imagenes descargadas de Flow, en orden, como S001.png, S002.png...

La otra mitad de `flow_prompts.py`. Toma las imagenes de una carpeta de
descargas POR ORDEN DE DESCARGA (fecha de modificacion, la mas antigua
primero), les pone el id del plano que toca segun `flow/planos.json` y las
deja en `flow/imagenes/`, que es la carpeta que el modo 'adoptar' lee. Si el
video tiene reparto, las primeras son las hojas de personaje (`ptolomeo.png`...)
y detras van los planos: el mismo orden que `prompts.txt`.

    python herramientas/flow_renombrar.py <proyecto> <carpeta_descargas>
    python herramientas/flow_renombrar.py <proyecto> <carpeta> --aplicar
    python herramientas/flow_renombrar.py <proyecto> <carpeta> --desde S009 --aplicar

Sin --aplicar solo ensena el reparto: que fichero va a que plano, con la frase
que se narra al lado, para mirarlo antes de copiar nada. Los originales no se
tocan nunca.

--desde sirve para ir por tandas: si las 8 primeras ya estan, se descargan las
siguientes en otra carpeta (o se vacia la de antes) y se empieza en S009.

EL TAMANO. Flow da 16:9 y el Estudio trabaja a 1536x1024 (3:2): el render amplia
esa imagen y recorta dentro una ventana 16:9 para el zoom. Se RECORTA al centro
hasta 3:2 (se pierde un 8 % por cada lado) en vez de estirar o meter bandas:
estirar deforma, y una banda negra acabaria dentro del video. Lo importante de
cada imagen, al centro.

POR NOMBRE. Si los ficheros ya se llaman como su plano (`S001.png`,
`ptolomeo.jpg`...), que es como los baja la extension de Chrome
(herramientas/flow_extension), se emparejan por NOMBRE y el orden de descarga
deja de importar. Basta con que uno se llame asi para usar este modo.

No sobrescribe un plano que ya exista salvo con --sobrescribir: una imagen
buena de Flow cuesta tiempo, y un reparto mal contado la pisaria sin avisar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flow_prompts import carpeta_flow, carpeta_proyecto  # noqa: E402
from pasos import flow  # noqa: E402

# La logica vive en pasos/flow.py, que es lo mismo que usa la pantalla con
# «Importar de Flow».
TAMANO = flow.TAMANO
EXTENSIONES = flow.EXTENSIONES
descargas = flow.imagenes_en
por_nombre = flow.por_nombre
encajar = flow.encajar


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("proyecto", help="id del proyecto o ruta de su carpeta")
    ap.add_argument("descargas", help="carpeta con las imagenes bajadas de Flow")
    ap.add_argument("--desde", help="primer plano de esta tanda (p. ej. S009)")
    ap.add_argument("--aplicar", action="store_true",
                    help="copiar de verdad (sin esto solo se ensena el reparto)")
    ap.add_argument("--sobrescribir", action="store_true",
                    help="pisar planos que ya tengan imagen")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dir_flow = carpeta_flow(carpeta_proyecto(args.proyecto))
    ruta_planos = os.path.join(dir_flow, "planos.json")
    if not os.path.exists(ruta_planos):
        raise SystemExit("no hay flow/planos.json: exporta antes los prompts con "
                         "herramientas/flow_prompts.py")
    with open(ruta_planos, encoding="utf-8") as fh:
        planos = json.load(fh)["planos"]
    ids = [p["id"] for p in planos]
    frases = {p["id"]: p["narracion"] for p in planos}
    if args.desde:
        # sin distinguir mayusculas: los planos son S009 y las hojas de
        # personaje van por su nombre en minusculas
        bajos = [i.lower() for i in ids]
        desde = args.desde.strip().lower()
        if desde not in bajos:
            raise SystemExit(f"{args.desde} no es un plano con imagen de este "
                             f"video (mira flow/prompts.txt)")
        ids = ids[bajos.index(desde):]

    if not os.path.isdir(args.descargas):
        raise SystemExit(f"no existe la carpeta {args.descargas}")
    ficheros = descargas(args.descargas)
    if not ficheros:
        raise SystemExit(f"no hay imagenes en {args.descargas}")

    destino_dir = os.path.join(dir_flow, "imagenes")
    os.makedirs(destino_dir, exist_ok=True)
    reparto = por_nombre(ficheros, ids)
    nombrados = bool(reparto)
    if nombrados:
        print("los ficheros se llaman como los planos: se emparejan por nombre\n")
    else:
        reparto = list(zip(ids, ficheros))
    for sid, fichero in reparto:
        existe = os.path.exists(os.path.join(destino_dir, f"{sid}.png"))
        marca = "  (ya tiene imagen)" if existe else ""
        print(f"{sid} <- {os.path.basename(fichero)}{marca}")
        print(f"       {frases[sid][:90]}")

    if nombrados:
        usados = {f for _, f in reparto}
        sueltos = [os.path.basename(f) for f in ficheros if f not in usados]
        pendientes = [i for i in ids if i not in dict(reparto)]
        if sueltos:
            print(f"\nAVISO: {len(sueltos)} ficheros no se llaman como ningun "
                  f"plano y se ignoran: {', '.join(sueltos[:8])}")
        if pendientes:
            print(f"\nfaltan {len(pendientes)} planos: "
                  f"{', '.join(pendientes[:12])}"
                  + (" ..." if len(pendientes) > 12 else ""))
    elif len(ficheros) > len(ids):
        print(f"\nAVISO: sobran {len(ficheros) - len(ids)} imagenes: "
              + ", ".join(os.path.basename(f) for f in ficheros[len(ids):]))
    elif len(ficheros) < len(ids):
        print(f"\nfaltan {len(ids) - len(ficheros)} planos por descargar "
              f"(el siguiente seria {ids[len(ficheros)]})")

    if not args.aplicar:
        print("\nno se ha copiado nada. Si el reparto esta bien, repite con --aplicar")
        return
    copiadas = saltadas = 0
    for sid, fichero in reparto:
        destino = os.path.join(destino_dir, f"{sid}.png")
        if os.path.exists(destino) and not args.sobrescribir:
            saltadas += 1
            continue
        encajar(fichero, destino)
        copiadas += 1
    print(f"\n{copiadas} copiadas a {destino_dir}"
          + (f"; {saltadas} saltadas porque ya tenian imagen (--sobrescribir)"
             if saltadas else ""))
    todos = [p["id"] for p in planos]
    faltan = [s for s in todos
              if not os.path.exists(os.path.join(destino_dir, f"{s}.png"))]
    print("todas las imagenes del video estan listas" if not faltan
          else f"faltan {len(faltan)} de {len(todos)}: {', '.join(faltan[:12])}"
               + (" ..." if len(faltan) > 12 else ""))


if __name__ == "__main__":
    main()
