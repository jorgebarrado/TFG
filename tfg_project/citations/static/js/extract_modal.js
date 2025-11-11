// citations/static/js/extract_modal.js
(() => {
  // --- Elementos del DOM (IDs según tu modal) ---
  const form       = document.getElementById('extract-form');
  const fileInput  = document.getElementById('extract-file');
  const engineSel  = document.getElementById('extract-engine');
  const debugChk   = document.getElementById('extract-debug');
  const btnSubmit  = document.getElementById('extract-btn');

  const alertBox   = document.getElementById('extract-alert');
  const summaryBox = document.getElementById('extract-summary');
  const resultsBox = document.getElementById('extract-results');
  const tracePre   = document.getElementById('extract-trace');

  const ENDPOINT = '/citations/api/extract-citations/';

  if (!form) return; // por si la modal no está en esta vista

  function hideAllFeedback() {
    alertBox.classList.add('d-none');
    summaryBox.classList.add('d-none');
    resultsBox.classList.add('d-none');
    tracePre.classList.add('d-none');
    alertBox.textContent = '';
    summaryBox.textContent = '';
    resultsBox.innerHTML = '';
    tracePre.textContent = '';
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

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    hideAllFeedback();

    const file = fileInput?.files?.[0];
    if (!file) {
      alertBox.textContent = 'Selecciona un PDF.';
      alertBox.classList.remove('d-none');
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

      if (data.trace) {
        tracePre.textContent = JSON.stringify(data.trace, null, 2);
        tracePre.classList.remove('d-none');
      }

      wireCardActions();
    } catch (e) {
      alertBox.textContent = 'Error de red o de servidor al extraer citas.';
      alertBox.classList.remove('d-none');
    } finally {
      btnSubmit.disabled = false;
      btnSubmit.textContent = originalText;
    }
  });
})();
