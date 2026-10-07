// La siguiente descarga de Flow, con el nombre del plano.
//
// El panel «arma» un plano (`estudioFlowArmado` en chrome.storage) y la
// persona descarga la imagen con el boton de descarga de la propia Flow. Aqui
// solo se le cambia el nombre: `estudio_flow/<proyecto>/<id>.<ext>`, dentro de
// la carpeta de Descargas. No se mira la pagina de Flow para nada: lo unico de
// lo que depende es de la API de descargas de Chrome, que no cambia cuando
// Google rediseña Flow.
//
// UN DISPARO. Al renombrar una descarga se desarma, asi que si se bajan dos
// variantes seguidas la segunda cae en Descargas con su nombre de siempre y no
// pisa nada. El panel vuelve a armar al pasar de plano.
//
// Todo el estado vive en chrome.storage y no en variables: Chrome duerme el
// service worker cuando quiere, y una descarga a medias no puede perder a que
// plano iba.

const ARMADO = 'estudioFlowArmado';     // {proyecto, id} o nada
const EN_CURSO = 'estudioFlowEnCurso';  // id de descarga -> {proyecto, id}
const AVISO = 'estudioFlowDescarga';    // lo que el panel escucha al terminar

const EXT_DE_MIME = {
  'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/webp': 'webp',
};

function extension(item) {
  if (EXT_DE_MIME[item.mime]) return EXT_DE_MIME[item.mime];
  const m = /\.(png|jpe?g|webp)$/i.exec(item.filename || '');
  return m ? m[1].toLowerCase().replace('jpeg', 'jpg') : 'png';
}

const FLOW = /^(blob:)?https:\/\/([a-z0-9-]+\.)*(flow\.google\.com|flow-content\.google)(\/|$)/i;

// Una imagen que viene de Flow. Si la descarga dice de que pagina viene y no
// es Flow, no es nuestra; si no lo dice (un data: o un blob:), vale con que
// sea una imagen: armar ya es decir «lo proximo que baje es este plano».
function esDeFlow(item) {
  const imagen = /^image\//.test(item.mime || '') ||
    /^data:image\//i.test(item.url || '') ||
    /\.(png|jpe?g|webp)$/i.test(item.filename || '');
  if (!imagen) return false;
  if ([item.url, item.finalUrl].some(u => FLOW.test(u || ''))) return true;
  return !item.referrer || FLOW.test(item.referrer);
}

chrome.downloads.onDeterminingFilename.addListener((item, sugerir) => {
  chrome.storage.local.get([ARMADO, EN_CURSO], d => {
    const armado = d[ARMADO];
    if (!armado || !esDeFlow(item)) { sugerir(); return; }
    const enCurso = d[EN_CURSO] || {};
    enCurso[item.id] = armado;
    chrome.storage.local.set({ [ARMADO]: null, [EN_CURSO]: enCurso }, () => {
      sugerir({
        filename: `estudio_flow/${armado.proyecto}/${armado.id}.${extension(item)}`,
        conflictAction: 'overwrite',
      });
    });
  });
  return true;                    // el nombre se sugiere despues de leer storage
});

chrome.downloads.onChanged.addListener(cambio => {
  const fin = cambio.state && cambio.state.current;
  if (fin !== 'complete' && fin !== 'interrupted') return;
  chrome.storage.local.get(EN_CURSO, d => {
    const enCurso = d[EN_CURSO] || {};
    const plano = enCurso[cambio.id];
    if (!plano) return;
    delete enCurso[cambio.id];
    const aviso = Object.assign({}, plano, {
      ok: fin === 'complete',
      error: cambio.error ? cambio.error.current : null,
      cuando: Date.now(),
    });
    chrome.storage.local.set({ [EN_CURSO]: enCurso, [AVISO]: aviso });
  });
});
