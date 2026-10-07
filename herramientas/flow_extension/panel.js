// Estudio → Flow: el panel que va plano a plano.
//
// QUE HACE Y QUE NO. Enseña el plano que toca (id, frase narrada, quien sale)
// y su prompt con un boton de copiar, y «arma» ese plano: la siguiente imagen
// que se descargue de Flow la guarda fondo.js como
// `estudio_flow/<proyecto>/<id>`. Pegar el prompt, generar y descargar lo hace
// la persona, con los botones de la propia Flow.
//
// NO TOCA LA PAGINA DE FLOW. La version anterior escribia en la caja del
// prompt, buscaba la imagen nueva entre las de la pagina y la descargaba sola;
// las tres cosas dependian de como esta hecha Flow por dentro y fallaban sin
// avisar en cuanto algo no cuadraba. Este panel vive en su propia sombra y
// solo habla con chrome.storage: si Google rediseña Flow, sigue funcionando.

(() => {
  if (window.__estudioFlow) return;
  window.__estudioFlow = true;

  const CLAVE = 'estudioFlow';           // lo del panel: tanda, indice, hechos
  const ARMADO = 'estudioFlowArmado';    // lo lee fondo.js al descargar
  const AVISO = 'estudioFlowDescarga';   // lo escribe fondo.js al terminar

  let estado = {
    tanda: null,        // {proyecto, imagenes:[{id,tipo,prompt,narracion,personajes}]}
    indice: 0,
    hechos: {},         // id -> true cuando su descarga ha terminado
    pausado: false,     // sin armar: las descargas de Flow no se renombran
  };
  let armadoId = null;  // lo que de verdad hay armado en storage

  // Si la extension se recarga, este script se queda huerfano y cualquier
  // llamada a chrome.* lanza «Extension context invalidated».
  function vivo() {
    try { return !!chrome.runtime.id; } catch (_e) { return false; }
  }
  function huerfano() {
    avisar('La extensión se ha actualizado: recarga esta pestaña de Flow (F5).');
  }

  const guardar = () => {
    if (!vivo()) { huerfano(); return; }
    chrome.storage.local.set({ [CLAVE]: estado });
  };
  const cargar = () => new Promise(ok => chrome.storage.local.get([CLAVE, ARMADO], d => {
    if (d && d[CLAVE]) estado = Object.assign(estado, d[CLAVE]);
    armadoId = d && d[ARMADO] ? d[ARMADO].id : null;
    ok();
  }));

  function actual() {
    const lista = (estado.tanda && estado.tanda.imagenes) || [];
    return lista[estado.indice] || null;
  }

  // Arma el plano actual, o desarma si no hay ninguno o esta en pausa.
  function armar() {
    if (!vivo()) { huerfano(); return; }
    const x = actual();
    const valor = x && !estado.pausado ? { proyecto: estado.tanda.proyecto, id: x.id } : null;
    armadoId = valor ? valor.id : null;
    chrome.storage.local.set({ [ARMADO]: valor });
  }

  // ------------------------------------------------------------ el panel

  const raiz = document.createElement('div');
  raiz.id = 'estudio-flow';
  const sombra = raiz.attachShadow({ mode: 'open' });
  const hoja = new CSSStyleSheet();
  hoja.replaceSync(`
    :host { all: initial; }
    .caja { position: fixed; right: 16px; bottom: 90px; z-index: 2147483647;
      width: 340px; background: #1d1f23; color: #e8eaed; border: 1px solid #3c4043;
      border-radius: 12px; font: 13px/1.4 system-ui, sans-serif; box-shadow: 0 8px 24px #0008; }
    .cab { display: flex; align-items: center; justify-content: space-between;
      padding: 8px 12px; border-bottom: 1px solid #3c4043; cursor: move; font-weight: 600; }
    .cuerpo { padding: 10px 12px; display: grid; gap: 8px; }
    .plegada .cuerpo { display: none; }
    .id { font-size: 18px; font-weight: 700; }
    .narr { color: #bdc1c6; max-height: 60px; overflow: auto; white-space: pre-line; }
    textarea { font: 12px/1.35 system-ui, sans-serif; color: #e8eaed; background: #292b2f;
      border: 1px solid #5f6368; border-radius: 8px; padding: 6px; height: 90px; resize: vertical; }
    .aviso { background: #5c2b00; color: #ffd8a8; border-radius: 8px; padding: 6px 8px; }
    .ok { background: #0d3b1e; color: #b7f5c8; border-radius: 8px; padding: 6px 8px; }
    .armado { color: #8ab4f8; }
    .armado.no { color: #9aa0a6; }
    .aviso:empty, .ok:empty, .armado:empty { display: none; }
    .fila { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
    button { font: inherit; color: #e8eaed; background: #303134; border: 1px solid #5f6368;
      border-radius: 8px; padding: 4px 10px; cursor: pointer; }
    button.primario { background: #8ab4f8; color: #202124; border-color: #8ab4f8; font-weight: 600; }
    button:disabled { opacity: .45; cursor: default; }
    .barra { height: 6px; background: #3c4043; border-radius: 3px; overflow: hidden; }
    .barra > div { height: 100%; background: #8ab4f8; width: 0; }
    select { font: inherit; color: inherit; background: #303134; border: 1px solid #5f6368; border-radius: 6px; }
    input[type=file] { display: none; }
  `);
  sombra.adoptedStyleSheets = [hoja];
  sombra.innerHTML = `
    <div class="caja">
      <div class="cab"><span>Estudio → Flow</span><button id="plegar" title="Plegar">–</button></div>
      <div class="cuerpo">
        <div class="fila"><button id="cargar">Cargar tanda.json</button>
          <input type="file" id="fichero" accept=".json,application/json"></div>
        <div id="info"></div>
        <div class="barra"><div id="progreso"></div></div>
        <div class="id" id="actual"></div>
        <div class="narr" id="narracion"></div>
        <textarea id="prompt" readonly></textarea>
        <div class="fila">
          <button class="primario" id="copiar">Copiar prompt</button>
          <button id="anterior">‹</button><button id="siguiente">›</button>
          <select id="ir"></select>
        </div>
        <div class="fila"><span class="armado" id="armado"></span>
          <button id="pausa"></button></div>
        <div class="aviso" id="aviso"></div>
        <div class="ok" id="ok"></div>
      </div>
    </div>`;
  const $ = id => sombra.getElementById(id);

  function avisar(texto) { $('aviso').textContent = texto || ''; }
  function bien(texto) { $('ok').textContent = texto || ''; }

  function pintar() {
    const lista = (estado.tanda && estado.tanda.imagenes) || [];
    const hechos = lista.filter(x => estado.hechos[x.id]).length;
    $('info').textContent = estado.tanda
      ? `${estado.tanda.proyecto} · ${hechos} de ${lista.length} descargadas`
      : 'Carga el flow/tanda.json del proyecto (lo escribe flow_prompts.py).';
    $('progreso').style.width = lista.length ? `${100 * hechos / lista.length}%` : '0';
    const x = actual();
    $('actual').textContent = x
      ? `${x.id}${x.tipo === 'hoja' ? ' · hoja de personaje' : ''}${estado.hechos[x.id] ? ' ✓' : ''}`
      : (lista.length ? 'Tanda terminada' : '');
    const quienes = x && x.personajes && x.personajes.length
      ? `\nSale: ${x.personajes.join(', ')} (adjunta su hoja como ingrediente)` : '';
    $('narracion').textContent = x ? `${x.narracion || ''}${quienes}` : '';
    $('prompt').value = x ? x.prompt : '';
    $('prompt').hidden = !x;
    $('copiar').disabled = !x;
    $('anterior').disabled = !lista.length || estado.indice <= 0;
    $('siguiente').disabled = !lista.length || estado.indice >= lista.length;
    const arm = $('armado');
    arm.classList.toggle('no', !armadoId);
    arm.textContent = !x ? '' : armadoId
      ? `La próxima descarga de Flow se guardará como ${armadoId}.`
      : estado.pausado ? 'En pausa: las descargas de Flow no se renombran.'
        : 'Guardando la descarga…';
    $('pausa').hidden = !x;
    $('pausa').textContent = estado.pausado ? 'Reanudar' : 'Pausar';
    const ir = $('ir');
    ir.innerHTML = '';
    lista.forEach((y, i) => {
      const op = document.createElement('option');
      op.value = String(i);
      op.textContent = `${estado.hechos[y.id] ? '✓ ' : ''}${y.id}`;
      op.selected = i === estado.indice;
      ir.appendChild(op);
    });
  }

  // ------------------------------------------------------------ acciones

  async function copiar() {
    const x = actual();
    if (!x) return;
    avisar('');
    try {
      await navigator.clipboard.writeText(x.prompt);
    } catch (_e) {
      // sin permiso de portapapeles: se copia seleccionando el texto
      const caja = $('prompt');
      caja.focus(); caja.select();
      if (!document.execCommand('copy')) {
        avisar('No he podido copiar: el prompt está seleccionado, cópialo con Ctrl+C.');
        return;
      }
    }
    const extra = x.personajes && x.personajes.length
      ? ` Adjunta la hoja de ${x.personajes.join(', ')}.` : '';
    bien(`Prompt de ${x.id} copiado. Pégalo en Flow (Ctrl+V), genera y descarga la imagen.${extra}`);
  }

  function mover(a) {
    const lista = (estado.tanda && estado.tanda.imagenes) || [];
    estado.indice = Math.max(0, Math.min(lista.length, a));
    guardar(); armar(); avisar(''); bien(''); pintar();
  }

  // El siguiente que falte, no el siguiente a secas: si se volvio atras para
  // repetir uno, se sigue por donde se iba.
  function siguienteQueFalta(desde) {
    const lista = estado.tanda.imagenes;
    let i = desde;
    while (i < lista.length && estado.hechos[lista[i].id]) i++;
    return i;
  }

  function alTerminarDescarga(aviso) {
    if (!aviso || !estado.tanda || aviso.proyecto !== estado.tanda.proyecto) return;
    if (!aviso.ok) {
      avisar(`La descarga de ${aviso.id} no ha terminado (${aviso.error || 'interrumpida'}). ` +
             'Vuelve a descargarla: el plano sigue armado.');
      armar(); pintar();
      return;
    }
    estado.hechos[aviso.id] = true;
    const x = actual();
    if (x && x.id === aviso.id) estado.indice = siguienteQueFalta(estado.indice + 1);
    guardar(); armar(); avisar('');
    const sig = actual();
    bien(`${aviso.id} guardada.${sig ? ` Ahora ${sig.id}: copia su prompt.` : ' Tanda terminada.'}`);
    pintar();
  }

  // ------------------------------------------------------------ eventos

  $('cargar').onclick = () => $('fichero').click();
  $('fichero').onchange = async ev => {
    const f = ev.target.files && ev.target.files[0];
    if (!f) return;
    try {
      const datos = JSON.parse(await f.text());
      if (!datos || !Array.isArray(datos.imagenes) || !datos.proyecto) throw new Error('no parece un tanda.json');
      const misma = estado.tanda && estado.tanda.proyecto === datos.proyecto;
      // la misma tanda otra vez (re-exportada): se conserva lo ya descargado
      estado.tanda = datos;
      if (!misma) estado.hechos = {};
      estado.indice = siguienteQueFalta(0);
      guardar(); armar(); avisar('');
      bien(`${datos.imagenes.length} imágenes cargadas${misma ? ' (se conserva lo ya descargado)' : ''}.`);
      pintar();
    } catch (e) {
      avisar(`No he podido leer el fichero: ${e.message}`);
    }
    ev.target.value = '';
  };
  $('copiar').onclick = copiar;
  $('anterior').onclick = () => mover(estado.indice - 1);
  $('siguiente').onclick = () => mover(estado.indice + 1);
  $('ir').onchange = ev => mover(Number(ev.target.value));
  $('pausa').onclick = () => { estado.pausado = !estado.pausado; guardar(); armar(); pintar(); };
  $('plegar').onclick = () => sombra.querySelector('.caja').classList.toggle('plegada');

  // arrastrar el panel por la cabecera
  (() => {
    const caja = sombra.querySelector('.caja');
    let dx = 0, dy = 0, moviendo = false;
    sombra.querySelector('.cab').addEventListener('mousedown', e => {
      if (e.target.tagName === 'BUTTON') return;
      const r = caja.getBoundingClientRect();
      dx = e.clientX - r.left; dy = e.clientY - r.top; moviendo = true;
    });
    window.addEventListener('mousemove', e => {
      if (!moviendo) return;
      caja.style.left = `${e.clientX - dx}px`; caja.style.top = `${e.clientY - dy}px`;
      caja.style.right = 'auto'; caja.style.bottom = 'auto';
    });
    window.addEventListener('mouseup', () => { moviendo = false; });
  })();

  chrome.storage.onChanged.addListener((cambios, zona) => {
    if (zona !== 'local') return;
    if (cambios[ARMADO]) {
      const v = cambios[ARMADO].newValue;
      armadoId = v ? v.id : null;
      pintar();
    }
    if (cambios[AVISO]) alTerminarDescarga(cambios[AVISO].newValue);
  });

  cargar().then(() => {
    armar();
    pintar();
    document.body.appendChild(raiz);
  });
})();
