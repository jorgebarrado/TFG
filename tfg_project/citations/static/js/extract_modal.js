// Minimal JS for the "extractModal" (engine + debug + render)
(() => {
  const FORM      = document.getElementById('extract-form');
  const FILE      = document.getElementById('extract-file');
  const ENGINE    = document.getElementById('extract-engine');
  const DEBUG     = document.getElementById('extract-debug');

  const BTN       = document.getElementById('extract-btn');
  const ALERT     = document.getElementById('extract-alert');
  const SUMMARY   = document.getElementById('extract-summary');
  const RESULTS   = document.getElementById('extract-results');
  const TRACEPRE  = document.getElementById('extract-trace');

  const EXTRACT_URL = '/citations/api/extract-citations/';

  function showAlert(msg) {
    ALERT.textContent = msg || 'Error';
    ALERT.classList.remove('d-none');
  }
  function hideAlert() { ALERT.classList.add('d-none'); }

  function escapeHTML(s) {
    return (s ?? '').toString()
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;');
  }
  function highlightRefs(str) {
    return escapeHTML(str).replace(/\[(\d+)\]/g, '<mark>[$1]</mark>');
  }

  function toFlatArray(data) {
    // Soporta {"contexts":[...]}, dict {"1":[...]}, o lista ya plana
    if (data && Array.isArray(data.contexts)) {
      return data.contexts.map((raw, i) => ({
        ref: Number(raw.ref ?? raw.reference ?? 0),
        idx: i + 1,
        snippet: raw.snippet ?? raw.fragment ?? '',
        paragraph: raw.paragraph ?? '',
        start: raw.start ?? null,
        end: raw.end ?? null,
        raw
      }));
    }
    if (data && !Array.isArray(data) && typeof data === 'object') {
      const flat = [];
      Object.keys(data).forEach((k) => {
        const arr = Array.isArray(data[k]) ? data[k] : [];
        arr.forEach((item, i) => {
          flat.push({
            ref: Number(k),
            idx: i + 1,
            snippet: item.snippet ?? item.fragment ?? '',
            paragraph: item.paragraph ?? '',
            start: item.start ?? null,
            end: item.end ?? null,
            raw: item
          });
        });
      });
      return flat;
    }
    if (Array.isArray(data)) return data;
    return [];
  }

  function render(list) {
    RESULTS.innerHTML = '';
    if (!list.length) {
      RESULTS.classList.add('d-none');
      return;
    }
    const frag = document.createDocumentFragment();
    list.forEach((item) => {
      const div = document.createElement('div');
      div.className = 'border rounded p-3';
      div.innerHTML = `
        <div class="fw-semibold mb-1">Ref [${item.ref}] · Fragmento ${item.idx}</div>
        <div class="mb-2" style="white-space:pre-wrap">${highlightRefs(item.snippet || '')}</div>

        <a href="#" class="small" data-action="toggle-paragraph">► Ver párrafo completo</a>
        <div class="mt-2" data-target="paragraph" hidden>
          <div style="white-space:pre-wrap">${escapeHTML(item.paragraph || '')}</div>
        </div>

        <div class="mt-2 d-flex gap-2 flex-wrap">
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-snippet">Copiar fragmento</button>
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-paragraph">Copiar párrafo</button>
          <button class="btn btn-outline-secondary btn-sm" data-action="view-json">Ver JSON</button>
        </div>
      `;
      div.dataset.payload = JSON.stringify(item.raw ?? item);
      frag.appendChild(div);
    });
    RESULTS.appendChild(frag);
    RESULTS.classList.remove('d-none');
  }

  RESULTS?.addEventListener('click', (e) => {
    const el = e.target.closest('button,a');
    if (!el) return;
    const card = el.closest('.border.rounded.p-3');
    const payload = (() => {
      try { return JSON.parse(card?.dataset?.payload || '{}'); } catch { return {}; }
    })();

    if (el.dataset.action === 'toggle-paragraph') {
      e.preventDefault();
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
    if (el.dataset.action === 'copy-snippet') {
      navigator.clipboard?.writeText(payload.snippet ?? payload.fragment ?? '');
    }
    if (el.dataset.action === 'copy-paragraph') {
      navigator.clipboard?.writeText(payload.paragraph ?? '');
    }
    if (el.dataset.action === 'view-json') {
      alert(JSON.stringify(payload, null, 2));
    }
  });

  FORM?.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideAlert();
    SUMMARY.classList.add('d-none');
    RESULTS.classList.add('d-none');
    TRACEPRE.classList.add('d-none');

    const file = FILE?.files?.[0];
    if (!file) { showAlert('Selecciona un PDF.'); return; }

    BTN.disabled = true;
    const original = BTN.innerHTML;
    BTN.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>Procesando…`;

    try {
      const fd = new FormData();
      fd.append('manuscript', file);
      fd.append('engine', (ENGINE?.value || 'auto'));
      if (DEBUG?.checked) fd.append('debug', '1');

      const res = await fetch(EXTRACT_URL, { method: 'POST', body: fd });
      const data = await res.json();

      if (!res.ok || data?.error) {
        showAlert(data?.error || 'Error procesando el archivo.');
        return;
      }

      // Cabecera-resumen
      const count = Number(data.count ?? 0);
      const engineUsed = data.engine_used ?? 'auto';
      SUMMARY.textContent = `${count} citas detectadas · motor: ${engineUsed}`;
      SUMMARY.classList.remove('d-none');

      // Traza
      if (Array.isArray(data.trace) && data.trace.length) {
        TRACEPRE.textContent = JSON.stringify(data.trace, null, 2);
        TRACEPRE.classList.remove('d-none');
      }

      // Render resultados
      render(toFlatArray(data));
    } catch {
      showAlert('Error de red o procesando el archivo.');
    } finally {
      BTN.disabled = false;
      BTN.innerHTML = original;
    }
  });
})();
