// citations/static/js/extract_modal.js
(() => {
  // --- Elementos del DOM (IDs según tu modal) ---
  const form       = document.getElementById('extract-form');
  const fileInput  = document.getElementById('extract-file');
  const engineSel  = document.getElementById('extract-engine');
  const debugChk   = document.getElementById('extract-debug');
  const btnSubmit  = document.getElementById('extract-btn');
  const readerBtn  = document.getElementById('extract-reader-btn');
  const debugDownloadBtn = document.getElementById('extract-debug-download-btn');

  const alertBox   = document.getElementById('extract-alert');
  const summaryBox = document.getElementById('extract-summary');
  const resultsBox = document.getElementById('extract-results');
  const tracePre   = document.getElementById('extract-trace');
  const modalEl    = document.getElementById('extractModal');

  const ENDPOINT = '/citations/api/extract-citations/';
  const ENGINES_ENDPOINT = '/citations/api/extractor-engines/';
  const READER_PREVIEW = '/citations/reader/preview/';
  const READER_PAYLOAD_DB = 'citecheck-reader-payloads';
  const READER_PAYLOAD_STORE = 'payloads';
  const READER_PAYLOAD_SESSION_KEY = 'citecheck.reader.payload';

  if (!form) return; // por si la modal no está en esta vista

  let extractionResult = null;

  function hideAllFeedback() {
    alertBox.classList.add('d-none');
    summaryBox.classList.add('d-none');
    resultsBox.classList.add('d-none');
    tracePre.classList.add('d-none');
    alertBox.textContent = '';
    summaryBox.textContent = '';
    resultsBox.innerHTML = '';
    tracePre.textContent = '';
    if (debugDownloadBtn) {
      debugDownloadBtn.dataset.downloadUrl = '';
      debugDownloadBtn.dataset.filename = '';
      debugDownloadBtn.disabled = true;
      debugDownloadBtn.classList.add('d-none');
    }
  }

  function enableDebugDownload(referenceDebug) {
    if (!debugDownloadBtn) return;
    const downloadUrl = String(referenceDebug?.download_url || '').trim();
    const filename = String(referenceDebug?.filename || 'reference_debug.json').trim();
    debugDownloadBtn.dataset.downloadUrl = downloadUrl;
    debugDownloadBtn.dataset.filename = filename || 'reference_debug.json';
    debugDownloadBtn.disabled = !downloadUrl;
    debugDownloadBtn.classList.toggle('d-none', !downloadUrl);
  }

  function syncButton() {
    if (!btnSubmit || !engineSel) return;
    btnSubmit.disabled = !engineSel.value;
  }

  function normalizeSnippetType(value) {
    const t = String(value || '').toLowerCase();
    if (t === 'numeric' || t === 'bracket') return 'bracket';
    if (t === 'author-year' || t === 'authoryear' || t === 'author_year') return 'authoryear';
    if (t === 'doi') return 'doi';
    return 'bracket';
  }

  function buildExtractionResult(data) {
    const list = Array.isArray(data?.results) ? data.results : [];
    const snippets = list
      .map((item, index) => {
        const pageNum = Number(item?.page);
        const page = Number.isFinite(pageNum) && pageNum > 0 ? pageNum : null;
        const snippet =
          item?.snippet ||
          item?.fragment ||
          item?.raw?.snippet ||
          item?.raw?.match ||
          '';
        if (!snippet) return null;
        return {
          id: item?.id || `${item?.ref || 'hit'}-${item?.idx || index + 1}`,
          page,
          snippet,
          type: normalizeSnippetType(item?.type || item?.pattern || item?.kind),
          confidence: Number(item?.confidence || 0),
        };
      })
      .filter(Boolean);

    const baseStats = data?.stats && typeof data.stats === 'object' ? data.stats : {};
    const stats = {
      pages_total: Number(baseStats.pages_total || 0),
      snippets_total:
        typeof baseStats.snippets_total === 'number'
          ? baseStats.snippets_total
          : (typeof data?.summary?.count === 'number' ? data.summary.count : list.length),
      references_total: Number(baseStats.references_total || 0),
      dois_total: Number(baseStats.dois_total || 0),
      engine_used: baseStats.engine_used || data?.engine_used || '',
      time_ms: Number.isFinite(Number(baseStats.time_ms))
        ? Number(baseStats.time_ms)
        : (Number.isFinite(Number(data?.time_ms)) ? Number(data.time_ms) : null),
      references_numbered: Boolean(baseStats.references_numbered),
    };
    const references = Array.isArray(data?.references) ? data.references : [];
    return { snippets, stats, references };
  }

  function buildEngineOptions(engines) {
    if (!engineSel) return;
    engineSel.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.disabled = true;
    placeholder.selected = true;
    placeholder.textContent = 'Selecciona una herramienta...';
    engineSel.appendChild(placeholder);

    (engines || []).forEach((engine) => {
      if (!engine || !engine.key) return;
      const opt = document.createElement('option');
      opt.value = engine.key;
      opt.textContent = engine.label || engine.key;
      if (engine.available === false) {
        opt.disabled = true;
        opt.textContent = `${opt.textContent} (Proximamente)`;
      }
      engineSel.appendChild(opt);
    });
  }

  async function loadEngines() {
    if (!engineSel) return;
    buildEngineOptions([]);
    syncButton();

    try {
      const res = await fetch(ENGINES_ENDPOINT, { method: 'GET' });
      if (!res.ok) throw new Error('engine list');
      const data = await res.json();
      const engines = Array.isArray(data.engines) ? data.engines : [];
      buildEngineOptions(engines);
      if (!engines.length) {
        alertBox.textContent = 'No hay motores disponibles.';
        alertBox.classList.remove('d-none');
      }
    } catch (e) {
      buildEngineOptions([]);
      alertBox.textContent = 'No se pudieron cargar las herramientas de extraccion.';
      alertBox.classList.remove('d-none');
    } finally {
      syncButton();
    }
  }

  function escapeHTML(s) {
    return (s ?? '').toString()
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;');
  }

  function highlightRefs(str) {
    return escapeHTML(str).replace(/\[(\d+)\]/g, '<mark>[$1]</mark>');
  }

  function cardHTML(item) {
    const header    = `Ref [${item.ref}] · Fragmento ${item.idx}`;
    const snippet   = highlightRefs(item.snippet || '');
    const paragraph = escapeHTML(item.paragraph || '');
    return `
      <div class="ce-card border rounded p-2 mb-2">
        <div class="fw-semibold mb-1">${header}</div>
        <div class="ce-snippet">${snippet}</div>

        <div class="mt-2 d-flex flex-wrap gap-2">
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-snippet">Copiar fragmento</button>
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-paragraph">Copiar párrafo</button>
          <button class="btn btn-outline-secondary btn-sm" data-action="view-json">Ver JSON</button>
        </div>

        <div class="mt-2">
          <a href="#" class="small" data-action="toggle-paragraph">► Ver párrafo completo</a>
          <div class="mt-2" data-target="paragraph" hidden>
            <div class="ce-snippet">${paragraph}</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderResults(data) {
    // data.results es una lista aplanada [{ref, idx, snippet, paragraph, ...}, ...]
    const list = Array.isArray(data.results) ? data.results : [];
    if (!list.length) {
      summaryBox.textContent = `0 citas detectadas (motor: ${data.engine_used || '—'})`;
      summaryBox.classList.remove('d-none');
      return;
    }

    const frag = document.createDocumentFragment();
    list.forEach(item => {
      const wrap = document.createElement('div');
      wrap.innerHTML = cardHTML(item);
      // Guarda el payload crudo por si el usuario pulsa “Ver JSON”
      wrap.firstElementChild.dataset.payload = JSON.stringify(item.raw ?? item);
      frag.appendChild(wrap.firstElementChild);
    });
    resultsBox.appendChild(frag);

    summaryBox.textContent = `${list.length} citas detectadas · motor: ${data.engine_used || '—'}`;
    summaryBox.classList.remove('d-none');
    resultsBox.classList.remove('d-none');
  }

  function wireCardActions() {
    resultsBox.addEventListener('click', (ev) => {
      const el = ev.target.closest('button, a');
      if (!el) return;

      const card = el.closest('.ce-card');
      const payload = (() => {
        try { return JSON.parse(card?.dataset.payload || '{}'); } catch { return {}; }
      })();

      if (el.dataset.action === 'copy-snippet') {
        const t = payload.snippet ?? payload.fragment ?? '';
        navigator.clipboard?.writeText(t).catch(() => {});
      }
      if (el.dataset.action === 'copy-paragraph') {
        const t = payload.paragraph ?? '';
        navigator.clipboard?.writeText(t).catch(() => {});
      }
      if (el.dataset.action === 'view-json') {
        alert(JSON.stringify(payload, null, 2));
      }
      if (el.dataset.action === 'toggle-paragraph') {
        ev.preventDefault();
        const box = card.querySelector('[data-target="paragraph"]');
        const opened = !box.hasAttribute('hidden');
        if (opened) {
          box.setAttribute('hidden', '');
          el.textContent = '► Ver párrafo completo';
        } else {
          box.removeAttribute('hidden');
          el.textContent = '▼ Ocultar párrafo completo';
        }
      }
    }, { once: true }); // nos suscribimos una vez por apertura de modal
  }

  function openPayloadDb() {
    return new Promise((resolve, reject) => {
      const req = window.indexedDB.open(READER_PAYLOAD_DB, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(READER_PAYLOAD_STORE)) {
          db.createObjectStore(READER_PAYLOAD_STORE);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('indexeddb_open_failed'));
    });
  }

  function writePayloadToDb(db, key, payload) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(READER_PAYLOAD_STORE, 'readwrite');
      tx.objectStore(READER_PAYLOAD_STORE).put(payload, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error('indexeddb_write_failed'));
    });
  }

  async function persistReaderPayload(file, dataPayload) {
    const payloadKey = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    const db = await openPayloadDb();
    await writePayloadToDb(db, payloadKey, {
      file,
      createdAt: Date.now(),
    });
    db.close();
    try {
      sessionStorage.setItem(
        `${READER_PAYLOAD_SESSION_KEY}:${payloadKey}`,
        JSON.stringify(dataPayload)
      );
    } catch (e) {
      // noop
    }
    return payloadKey;
  }

  async function openReaderPreview() {
    const file = fileInput?.files?.[0];
    if (!file) {
      alertBox.textContent = 'Selecciona un PDF.';
      alertBox.classList.remove('d-none');
      return;
    }

    const payload = {
      snippets: extractionResult?.snippets || [],
      references: extractionResult?.references || [],
      stats: extractionResult?.stats || null,
    };
    try {
      const payloadKey = await persistReaderPayload(file, payload);
      const readerUrl = `${READER_PREVIEW}?payload=${encodeURIComponent(payloadKey)}`;
      window.location.assign(readerUrl);
    } catch (e) {
      window.location.assign(READER_PREVIEW);
    }
  }

  if (engineSel) {
    engineSel.addEventListener('change', syncButton);
  }
  if (readerBtn) {
    readerBtn.addEventListener('click', openReaderPreview);
  }
  if (debugDownloadBtn) {
    debugDownloadBtn.addEventListener('click', () => {
      const downloadUrl = String(debugDownloadBtn.dataset.downloadUrl || '').trim();
      if (!downloadUrl) return;
      const link = document.createElement('a');
      link.href = downloadUrl;
      if (debugDownloadBtn.dataset.filename) {
        link.download = debugDownloadBtn.dataset.filename;
      }
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    });
  }
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      extractionResult = null;
    });
  }
  if (modalEl) {
    modalEl.addEventListener('show.bs.modal', () => {
      if (fileInput) {
        fileInput.value = '';
      }
      extractionResult = null;
      hideAllFeedback();
      loadEngines();
    });
  } else {
    loadEngines();
  }
  syncButton();

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    hideAllFeedback();
    extractionResult = null;

    const file = fileInput?.files?.[0];
    if (!file) {
      alertBox.textContent = 'Selecciona un PDF.';
      alertBox.classList.remove('d-none');
      return;
    }
    if (!engineSel?.value) {
      alertBox.textContent = 'Selecciona una herramienta de extraccion.';
      alertBox.classList.remove('d-none');
      syncButton();
      return;
    }

    btnSubmit.disabled = true;
    const originalText = btnSubmit.textContent;
    btnSubmit.textContent = 'Procesando…';

    try {
      const fd = new FormData();
      fd.append('manuscript', file);
      fd.append('engine', engineSel.value);
      fd.append('debug', debugChk.checked ? '1' : '0');
      fd.append('debug_reference_detection', debugChk.checked ? '1' : '0');

      const res  = await fetch(ENDPOINT, { method: 'POST', body: fd });
      const data = await res.json();

      // --- Manejo de error del servidor (ok:false) ---
      if (!data.ok) {
        alertBox.textContent = data.error || 'No se pudo extraer citas con el motor seleccionado.';
        alertBox.classList.remove('d-none');

        if (data.trace) {
          tracePre.textContent = JSON.stringify(data.trace, null, 2);
          tracePre.classList.remove('d-none');
        }
        return;
      }

      // --- OK: pintar resumen, resultados y (si procede) la traza ---
      renderResults(data);
      extractionResult = buildExtractionResult(data);
      if (data.reference_debug?.output_path) {
        summaryBox.textContent = `${summaryBox.textContent} · debug: ${data.reference_debug.output_path}`;
      }
      enableDebugDownload(data.reference_debug);

      if (data.trace) {
        tracePre.textContent = JSON.stringify(data.trace, null, 2);
        tracePre.classList.remove('d-none');
      }

      wireCardActions();
    } catch (e) {
      alertBox.textContent = 'Error de red o de servidor al extraer citas.';
      alertBox.classList.remove('d-none');
    } finally {
      btnSubmit.textContent = originalText;
      syncButton();
    }
  });
})();
