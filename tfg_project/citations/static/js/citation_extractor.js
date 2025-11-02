/* EN/ES: Extract citations UI renderer (PDF or TXT)
   - No inline JS. This file owns the whole behavior. */

(() => {
  const BTN_EXTRACT = document.getElementById('btn-extract');
  const BTN_JSON    = document.getElementById('btn-export-json');
  const BTN_CSV     = document.getElementById('btn-export-csv');
  const INPUT_FILE  = document.getElementById('manuscript');
  const RESULTS     = document.getElementById('results');
  const COUNT_LABEL = document.getElementById('count-label');

  let lastData = []; // estructura aplanada para exportar

  const EXTRACT_URL = '/citations/api/extract-citations/';

  function toFlatArray(data) {
    // A) dict con keys "1","2",...  -> aplanamos
    if (data && !Array.isArray(data) && typeof data === 'object') {
      const flat = [];
      Object.keys(data).forEach((key) => {
        const arr = Array.isArray(data[key]) ? data[key] : [];
        arr.forEach((item, i) => {
          flat.push({
            ref: Number(key),
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
    // B) ya viene como lista
    if (Array.isArray(data)) return data;
    return [];
  }

  function escapeHTML(s) {
    return (s ?? '').toString()
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;');
  }

  function highlightRefs(str) {
    // resalta [n] – super simple y efectivo
    return escapeHTML(str).replace(/\[(\d+)\]/g, '<mark>[$1]</mark>');
  }

  function cardHTML(item) {
    const header = `Ref [${item.ref}] · Fragmento ${item.idx}`;
    const snippet = highlightRefs(item.snippet || '');
    const paragraph = escapeHTML(item.paragraph || '');

    return `
      <div class="ce-card">
        <div class="ce-header fw-semibold mb-2">${header}</div>

        <div class="ce-snippet">${snippet}</div>

        <div class="ce-actions mt-2 d-flex flex-wrap gap-2">
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-snippet">
            Copiar fragmento
          </button>
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-paragraph">
            Copiar párrafo completo
          </button>
          <button class="btn btn-outline-secondary btn-sm" data-action="view-json">
            Ver JSON
          </button>
        </div>

        <div class="mt-2">
          <a href="#" class="ce-toggle small" data-action="toggle-paragraph">
            ► Ver párrafo completo
          </a>
          <div class="mt-2" data-target="paragraph" hidden>
            <div class="ce-snippet">${paragraph}</div>
          </div>
        </div>
      </div>
    `;
  }

  function render(list) {
    RESULTS.innerHTML = '';
    if (!list.length) {
      COUNT_LABEL.hidden = false;
      COUNT_LABEL.textContent = '0 citas detectadas';
      BTN_JSON.disabled = BTN_CSV.disabled = true;
      return;
    }

    const frag = document.createDocumentFragment();
    list.forEach(item => {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = cardHTML(item);
      // Guarda datos por si el usuario pulsa “Ver JSON”
      wrapper.firstElementChild.dataset.payload = JSON.stringify(item.raw ?? item);
      frag.appendChild(wrapper.firstElementChild);
    });
    RESULTS.appendChild(frag);

    COUNT_LABEL.hidden = false;
    COUNT_LABEL.textContent = `${list.length} citas detectadas`;
    BTN_JSON.disabled = BTN_CSV.disabled = false;
  }

  function copyToClipboard(txt) {
    navigator.clipboard?.writeText(txt).catch(() => {});
  }

  RESULTS.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button, a');
    if (!btn) return;

    const card = btn.closest('.ce-card');
    if (!card) return;

    const payload = (() => {
      try { return JSON.parse(card.dataset.payload || '{}'); }
      catch { return {}; }
    })();

    if (btn.dataset.action === 'copy-snippet') {
      copyToClipboard(payload.snippet ?? payload.fragment ?? '');
    }
    if (btn.dataset.action === 'copy-paragraph') {
      copyToClipboard(payload.paragraph ?? '');
    }
    if (btn.dataset.action === 'view-json') {
      alert(JSON.stringify(payload, null, 2));
    }
    if (btn.dataset.action === 'toggle-paragraph') {
      ev.preventDefault();
      const box = card.querySelector('[data-target="paragraph"]');
      const opened = !box.hasAttribute('hidden');
      if (opened) {
        box.setAttribute('hidden','');
        btn.textContent = '► Ver párrafo completo';
      } else {
        box.removeAttribute('hidden');
        btn.textContent = '▼ Ocultar párrafo completo';
      }
    }
  });

  BTN_EXTRACT?.addEventListener('click', async () => {
    const file = INPUT_FILE?.files?.[0];
    if (!file) {
      alert('Selecciona un archivo PDF o TXT.');
      return;
    }
    BTN_EXTRACT.disabled = true;
    BTN_EXTRACT.textContent = 'Procesando…';

    try {
      const fd = new FormData();
      fd.append('manuscript', file);
      const res = await fetch(EXTRACT_URL, { method: 'POST', body: fd });
      const data = await res.json();
      lastData = toFlatArray(data);
      render(lastData);
    } catch (e) {
      alert('Error procesando el archivo.');
    } finally {
      BTN_EXTRACT.disabled = false;
      BTN_EXTRACT.textContent = 'Extraer citas / Extract citations';
    }
  });

  // Exportar
  BTN_JSON?.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(lastData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: 'citations.json' });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });

  BTN_CSV?.addEventListener('click', () => {
    if (!lastData.length) return;
    const header = ['ref','idx','snippet','paragraph','start','end'];
    const rows = lastData.map(x => [
      x.ref, x.idx,
      (x.snippet || '').replaceAll('\n',' '),
      (x.paragraph || '').replaceAll('\n',' '),
      x.start ?? '', x.end ?? ''
    ]);
    const csv = [header, ...rows].map(r => r.map(v => `"${String(v).replaceAll('"','""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: 'citations.csv' });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });
})();
