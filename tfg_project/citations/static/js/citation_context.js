/* Context viewer for Semantic Scholar citations */

(() => {
  const MODAL_ID = 'contextModal';
  const RESULTS  = document.getElementById('ctx-results');
  const LOADING  = document.getElementById('ctx-loading');
  const ERRORBOX = document.getElementById('ctx-error');

  function show(el)  { el && el.classList.remove('d-none'); }
  function hide(el)  { el && el.classList.add('d-none');  }
  function htmlEscape(s){ return (s ?? '').toString()
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function openModal() {
    const el = document.getElementById(MODAL_ID);
    // Bootstrap 5
    const modal = window.bootstrap ? new bootstrap.Modal(el) : null;
    if (modal) modal.show();
  }

  async function fetchContext(params) {
    const url = new URL('/citations/api/get-citation-context/', window.location.origin);
    Object.entries(params).forEach(([k,v]) => {
      if (v != null && v !== '') url.searchParams.set(k, v);
    });
    const res = await fetch(url.toString(), { method: 'GET' });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = json?.error || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return json;
  }

  function renderResults(json) {
    RESULTS.innerHTML = '';
    const items = Array.isArray(json.contexts) ? json.contexts :
                  (Array.isArray(json.hits) ? json.hits : []);

    if (!items.length) {
      RESULTS.innerHTML = `<div class="text-muted">No se han encontrado párrafos que citen el artículo objetivo.</div>`;
      return;
    }

    const frag = document.createDocumentFragment();
    items.forEach((hit, i) => {
      const div = document.createElement('div');
      div.className = 'p-3 border rounded';
      div.innerHTML = `
        <div class="small text-muted mb-1">Coincidencia #${i+1}</div>
        <div class="mb-2"><strong>Fragmento:</strong> ${htmlEscape(hit.snippet || '')}</div>
        <div class="mb-0"><strong>Párrafo:</strong> ${htmlEscape(hit.paragraph || '')}</div>`;
      frag.appendChild(div);
    });
    RESULTS.appendChild(frag);
  }

  function showError(msg) {
    ERRORBOX.textContent = msg || 'Error inesperado.';
    show(ERRORBOX);
  }

  // Delegación de evento para los botones “View context”
  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-action="view-context"]');
    if (!btn) return;

    // Leer parámetros del botón
    const params = {
      citing_doi: btn.dataset.citingDoi || '',
      target_doi: btn.dataset.targetDoi || '',
      target_title: btn.dataset.targetTitle || '',
      target_first_author: btn.dataset.targetFirstAuthor || '',
      target_year: btn.dataset.targetYear || ''
    };

    // Abrir modal y estados
    openModal();
    hide(ERRORBOX);
    RESULTS.innerHTML = '';
    show(LOADING);

    try {
      const json = await fetchContext(params);
      renderResults(json);
      const traceBox = document.getElementById('ctx-trace');
      if (traceBox) {
        traceBox.classList.add('d-none');
        if (Array.isArray(json.trace)) {
            traceBox.innerHTML = json.trace.map(r => {
                const badge = r.status === 'ok' ? 'success' : (r.status === 'miss' ? 'secondary' : 'danger');
                return `<div><span class="badge text-bg-${badge} me-2">${r.status.toUpperCase()}</span><b>${r.step}</b> <span class="text-muted">${r.detail||''}</span></div>`;
            }).join('');
            traceBox.classList.remove('d-none');
        }
      }
    } catch (e) {
      showError(e.message);
    } finally {
      hide(LOADING);
    }
  });

  // Log para verificar que carga el JS
  console.log('[citation_context] cargado');
})();
