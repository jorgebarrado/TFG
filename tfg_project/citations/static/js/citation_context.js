/* EN/ES: Extract citations UI renderer (PDF or TXT) */
(() => {
  const MODAL_ID = 'contextModal';
  const RESULTS  = document.getElementById('ctx-results');
  const ERR_BOX  = document.getElementById('ctx-error');
  const LOADING  = document.getElementById('ctx-loading');
  const TRACEBOX = document.getElementById('ctx-trace');
  const CREATE_BTN = document.getElementById('ctx-create-report');

  const show = (el, on=true) => el && el.classList.toggle('d-none', !on);
  const esc  = (s='') => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  function renderTrace(trace) {
    if (!Array.isArray(trace) || !trace.length) {
      TRACEBOX.innerHTML = '';
      return;
    }
    const badge = (st) => ({
      ok:    '<span class="badge bg-success">OK</span>',
      miss:  '<span class="badge bg-secondary">NO</span>',
      error: '<span class="badge bg-danger">ERR</span>'
    })[st] || `<span class="badge bg-light text-dark">${esc(st)}</span>`;

    TRACEBOX.innerHTML = trace.map(x =>
      `<div>• ${badge(x.status)} <strong>${esc(x.step)}</strong> <span class="ms-1">${esc(x.detail || '')}</span></div>`
    ).join('');
  }

  async function fetchContext(payload) {
    const res = await fetch('/citations/api/get-citation-context/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }, // csrf_exempt en backend
      body: JSON.stringify(payload)
    });
    return await res.json();
  }

  function renderResults(data, targetDOI, citingDOI) {
    const hits = Array.isArray(data?.hits) ? data.hits : [];
    if (!hits.length) {
      RESULTS.innerHTML = '<div class="text-muted">No se han encontrado párrafos que citen el artículo objetivo.</div>';
      return;
    }
    RESULTS.innerHTML = hits.map(h => `
      <div class="border rounded p-2 mb-2">
        ${h.page ? `<div class="small text-muted">p.${esc(h.page)}</div>` : ''}
        <div class="fw-semibold">${esc(h.snippet || '')}</div>
        ${h.paragraph ? `<details class="mt-2"><summary>Ver párrafo</summary><div class="mt-1">${esc(h.paragraph)}</div></details>` : ''}
      </div>
    `).join('');

    if (CREATE_BTN) {
      const url = `/citations/new/?original_doi=${encodeURIComponent(targetDOI || '')}&incorrect_doi=${encodeURIComponent(citingDOI || '')}`;
      CREATE_BTN.href = url;
      CREATE_BTN.classList.remove('d-none');
    }
  }

  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-action="view-context"]');
    if (!btn) return;

    const citingDOI  = btn.getAttribute('data-citing-doi') || '';
    const targetDOI  = btn.getAttribute('data-target-doi') || '';
    const targetTitle = btn.getAttribute('data-target-title') || '';
    const targetFirstAuthor = btn.getAttribute('data-target-first-author') || '';
    const targetYear = btn.getAttribute('data-target-year') || '';

    const modalEl = document.getElementById(MODAL_ID);
    if (!modalEl) return;
    const bsModal = bootstrap.Modal.getOrCreateInstance(modalEl);
    bsModal.show();

    RESULTS.innerHTML = '';
    TRACEBOX.innerHTML = '';
    show(ERR_BOX, false);
    show(LOADING, true);
    if (CREATE_BTN) CREATE_BTN.classList.add('d-none');

    try {
      const payload = {
        citing_doi: citingDOI,
        target_doi: targetDOI || null,
        target_title: targetTitle || null,
        target_first_author: targetFirstAuthor || null,
        target_year: targetYear || null
      };
      const json = await fetchContext(payload);
      show(LOADING, false);

      renderTrace(json.trace);

      if (!json || json.ok === false) {
        ERR_BOX.textContent = json?.error || 'No se pudo obtener el contexto.';
        show(ERR_BOX, true);
        return;
      }
      renderResults(json, targetDOI, citingDOI);
    } catch (e) {
      show(LOADING, false);
      ERR_BOX.textContent = 'Error de red o servidor.';
      show(ERR_BOX, true);
    }
  });
})();
