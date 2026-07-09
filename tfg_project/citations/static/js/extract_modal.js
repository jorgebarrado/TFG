// citations/static/js/extract_modal.js
(() => {
  const rootScope = typeof window !== 'undefined' ? window : globalThis;
  const doc = typeof document !== 'undefined' ? document : null;
  const getEl = (id) => (doc ? doc.getElementById(id) : null);
  // --- Elementos del DOM (IDs según tu modal) ---
  const form       = getEl('extract-form');
  const fileInput  = getEl('extract-file');
  const engineSel  = getEl('extract-engine');
  const debugChk   = getEl('extract-debug');
  const btnSubmit  = getEl('extract-btn');
  const readerBtn  = getEl('extract-reader-btn');
  const debugDownloadBtn = getEl('extract-debug-download-btn');

  const alertBox   = getEl('extract-alert');
  const summaryBox = getEl('extract-summary');
  const resultsBox = getEl('extract-results');
  const tracePre   = getEl('extract-trace');
  const progressBox = getEl('extract-progress');
  const progressBar = getEl('extract-progress-bar');
  const progressLabel = getEl('extract-progress-label');
  const progressMeta = getEl('extract-progress-meta');
  const progressValue = getEl('extract-progress-value');
  const progressSpinner = getEl('extract-progress-spinner');
  const modalEl    = getEl('extractModal');

  const ENDPOINT = '/citations/api/extract-citations/';
  const ENGINES_ENDPOINT = '/citations/api/extractor-engines/';
  const READER_PREVIEW = '/citations/reader/preview/';
  const READER_PAYLOAD_DB = 'citecheck-reader-payloads';
  const READER_PAYLOAD_STORE = 'payloads';
  const READER_PAYLOAD_SESSION_KEY = 'citecheck.reader.payload';

  rootScope.__extractModalTestHooks = {
    normalizeReferenceRows,
    getReferencePanelNotice,
    renderReferencePanelHTML,
  };

  if (!form) return; // por si la modal no está en esta vista

  const debugEnabled = form.dataset.debugEnabled === 'true';
  let extractionResult = null;
  let progressTimer = null;
  let progressPercent = 0;
  let resultsActionsWired = false;
  let referencesPanelState = {
    model: null,
    query: '',
    selectedRefId: '',
    expandedMentionKey: '',
  };

  function getApproxProgressStep(value) {
    if (value < 18) return 5;
    if (value < 36) return 4;
    if (value < 54) return 3;
    if (value < 74) return 2;
    if (value < 88) return 1;
    return 0.4;
  }

  function getApproxProgressLabel(value) {
    if (value < 12) return 'Preparando PDF...';
    if (value < 28) return 'Subiendo PDF y preparando extraccion...';
    if (value < 46) return 'Leyendo paginas del documento...';
    if (value < 66) return 'Detectando referencias y citas...';
    if (value < 84) return 'Relacionando resultados...';
    return 'Finalizando la extraccion...';
  }

  function clearProgressTimer() {
    if (progressTimer) {
      window.clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function renderProgress(percent, label, meta, { complete = false } = {}) {
    if (!progressBox || !progressBar || !progressLabel || !progressMeta || !progressValue) {
      return;
    }
    const safePercent = Math.max(0, Math.min(100, Number(percent || 0)));
    progressBox.classList.remove('d-none');
    progressBox.classList.toggle('is-complete', complete);
    progressLabel.textContent = label || 'Extraccion en curso...';
    progressMeta.textContent = meta || 'Progreso aproximado';
    progressValue.textContent = `${Math.round(safePercent)}%`;
    progressBar.style.width = `${safePercent}%`;
    progressBar.classList.toggle('progress-bar-striped', !complete);
    progressBar.classList.toggle('progress-bar-animated', !complete);
    progressBar.classList.toggle('bg-success', complete);
    if (progressSpinner) {
      progressSpinner.classList.toggle('d-none', complete);
    }
    if (btnSubmit && btnSubmit.disabled) {
      btnSubmit.textContent = complete
        ? 'Extraccion completada'
        : `Extrayendo... ${Math.round(safePercent)}%`;
    }
  }

  function resetProgress() {
    clearProgressTimer();
    progressPercent = 0;
    if (!progressBox || !progressBar || !progressLabel || !progressMeta || !progressValue) {
      return;
    }
    progressBox.classList.add('d-none');
    progressBox.classList.remove('is-complete');
    progressLabel.textContent = 'Preparando extraccion...';
    progressMeta.textContent = 'Progreso aproximado';
    progressValue.textContent = '0%';
    progressBar.style.width = '0%';
    progressBar.classList.add('progress-bar-striped', 'progress-bar-animated');
    progressBar.classList.remove('bg-success');
    if (progressSpinner) {
      progressSpinner.classList.remove('d-none');
    }
  }

  function startProgress() {
    clearProgressTimer();
    progressPercent = 6;
    renderProgress(progressPercent, getApproxProgressLabel(progressPercent), 'Progreso aproximado');
    progressTimer = window.setInterval(() => {
      progressPercent = Math.min(94, progressPercent + getApproxProgressStep(progressPercent));
      renderProgress(progressPercent, getApproxProgressLabel(progressPercent), 'Progreso aproximado');
    }, 450);
  }

  function completeProgress() {
    clearProgressTimer();
    progressPercent = 100;
    renderProgress(progressPercent, 'Extraccion completada.', 'Progreso aproximado', {
      complete: true,
    });
  }

  function hideAllFeedback() {
    resetProgress();
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
    if (!debugEnabled) return;
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
    const enrichment =
      data?.enrichment && typeof data.enrichment === 'object' ? data.enrichment : null;
    const articleInfo =
      data?.article_info && typeof data.article_info === 'object' ? data.article_info : null;
    return { snippets, stats, references, enrichment, articleInfo };
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

  function escapeAttr(value) {
    return escapeHTML(value).replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  }

  function compactText(value) {
    return (value ?? '').toString().replace(/\s+/g, ' ').trim();
  }

  function normalizeNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function parseRefIndex(refId) {
    const match = String(refId || '').match(/^ref-(\d+)$/);
    if (!match) return null;
    const value = Number(match[1]);
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  function formatDisplayPage(page) {
    const value = normalizeNumber(page);
    if (value === null || value < 0) return 'p. -';
    return `p. ${value + 1}`;
  }

  function extractReferenceSummary(raw) {
    const cleaned = compactText(raw);
    if (!cleaned) {
      return { author: '', title: '' };
    }
    const stripped = cleaned.replace(/^\s*(\[(\d+)\]|(\d+)[\.\)])\s*/g, '');
    const formatAuthor = (value) => {
      const normalized = compactText(value);
      if (!normalized) return '';
      const firstChunk = normalized.split(';')[0].split(' and ')[0].trim();
      if (firstChunk.includes(',')) {
        const [lastName, rest] = firstChunk.split(',', 2);
        const initials = rest
          ? rest
              .trim()
              .split(/\s+/)
              .filter(Boolean)
              .map((token) => `${token[0].toUpperCase()}.`)
              .join(' ')
          : '';
        return initials ? `${lastName.trim()}, ${initials}` : lastName.trim();
      }
      const parts = firstChunk.split(/\s+/).filter(Boolean);
      if (parts.length >= 2) {
        return `${parts[parts.length - 1]}, ${parts[0][0].toUpperCase()}.`;
      }
      return firstChunk;
    };
    const firstPeriod = stripped.indexOf('. ');
    const authorPart =
      firstPeriod !== -1 ? stripped.slice(0, firstPeriod).trim() : '';
    let remainder =
      firstPeriod !== -1 ? stripped.slice(firstPeriod + 2).trim() : stripped;
    remainder = remainder.replace(/^[-:,;)\]]+\s*/, '').trim();
    let title = remainder ? remainder.split('. ')[0].trim() : '';
    if (!title) {
      const yearMatch = stripped.match(/\b(19|20)\d{2}\b/);
      if (yearMatch && yearMatch.index) {
        title = stripped.slice(0, yearMatch.index).trim();
        if (authorPart && title.startsWith(authorPart)) {
          title = title.slice(authorPart.length).trim();
        }
      }
    }
    return { author: formatAuthor(authorPart || stripped), title };
  }

  function normalizePageValue(rawPage, { oneBased = false } = {}) {
    const page = normalizeNumber(rawPage);
    if (page === null || page < 0) return null;
    return oneBased && page > 0 ? page - 1 : page;
  }

  function buildMentionFromResult(item, index) {
    const refIndex = normalizeNumber(
      item?.ref ?? item?.bracket_index ?? item?.index ?? item?.idx
    );
    const fallbackRefId = refIndex && refIndex > 0 ? `ref-${refIndex}` : `result-${index + 1}`;
    return {
      id: String(item?.id || `result-mention-${index + 1}`),
      ref_id: String(item?.ref_id || fallbackRefId),
      page: normalizePageValue(item?.page, { oneBased: true }),
      text: compactText(item?.snippet || item?.fragment || item?.paragraph || ''),
      paragraph: compactText(item?.paragraph || item?.context || item?.text || item?.snippet || item?.fragment || ''),
      rawPayload: item?.raw ?? item,
    };
  }

  function groupByRefId(items) {
    const grouped = new Map();
    items.forEach((item) => {
      const refId = String(item?.ref_id || '').trim();
      if (!refId) return;
      if (!grouped.has(refId)) grouped.set(refId, []);
      grouped.get(refId).push(item);
    });
    grouped.forEach((group) => {
      group.sort((a, b) => {
        const pageA = normalizeNumber(a?.page);
        const pageB = normalizeNumber(b?.page);
        if (pageA !== null && pageB !== null && pageA !== pageB) {
          return pageA - pageB;
        }
        return String(a?.id || '').localeCompare(String(b?.id || ''));
      });
    });
    return grouped;
  }

  function textField(value) {
    if (typeof value === 'string' || typeof value === 'number') {
      return compactText(value);
    }
    return '';
  }

  function getMentionText(mention) {
    return (
      textField(mention?.text) ||
      textField(mention?.snippet) ||
      textField(mention?.fragment) ||
      textField(mention?.paragraph)
    );
  }

  function getContextText(context) {
    return (
      textField(context?.text) ||
      textField(context?.paragraph) ||
      textField(context?.snippet) ||
      textField(context?.context)
    );
  }

  function findContextForMention(mention, contexts, mentionIndex) {
    const safeContexts = Array.isArray(contexts) ? contexts : [];
    const mentionId = String(mention?.id || '').trim();
    if (mentionId) {
      const expectedContextId = `citation-context-${mentionId}`;
      const exact = safeContexts.find((context) => {
        const contextId = String(context?.id || '').trim();
        const linkedMentionId = String(context?.mention_id || context?.citation_id || '').trim();
        return contextId === expectedContextId || linkedMentionId === mentionId;
      });
      if (exact) return exact;
    }

    const mentionPage = normalizePageValue(mention?.page);
    const samePageContexts = mentionPage === null
      ? []
      : safeContexts.filter((context) => normalizePageValue(context?.page) === mentionPage);

    return samePageContexts[mentionIndex] || samePageContexts[0] || safeContexts[mentionIndex] || null;
  }

  function enrichMentionsWithContexts(mentions, contexts) {
    const safeMentions = Array.isArray(mentions) ? mentions : [];
    return safeMentions.map((mention, index) => {
      const rawPayload = mention?.rawPayload || mention?.raw || {};
      const mentionText = getMentionText(mention);
      const linkedContext = findContextForMention(mention, contexts, index);
      const paragraphText =
        textField(mention?.paragraph) ||
        textField(mention?.context) ||
        textField(rawPayload?.paragraph) ||
        textField(rawPayload?.context) ||
        textField(rawPayload?.full_text) ||
        getContextText(linkedContext) ||
        mentionText;

      return {
        ...mention,
        text: mentionText || paragraphText,
        paragraph: paragraphText || mentionText,
        contextPayload: linkedContext,
      };
    });
  }

  function normalizeVisualReference(entry, index, mentionsByRefId, contextsByRefId) {
    const fallbackIndex = normalizeNumber(entry?.index) || index + 1;
    const refId = String(entry?.ref_id || entry?.id || `ref-${fallbackIndex}`).trim();
    const parsedIndex = parseRefIndex(refId);
    const text = compactText(entry?.text || entry?.raw || entry?.citation || '');
    const summary = extractReferenceSummary(text);
    const contexts = contextsByRefId.get(refId) || [];
    const mentions = enrichMentionsWithContexts(mentionsByRefId.get(refId) || [], contexts);
    return {
      ref_id: refId,
      index: parsedIndex || fallbackIndex,
      page: normalizePageValue(entry?.page),
      text,
      title: compactText(entry?.title || entry?.display_title || summary.title),
      author: compactText(entry?.author || entry?.display_author || summary.author),
      doi: compactText(entry?.doi),
      structure_source: compactText(entry?.structure_source),
      mentions_total: mentions.length,
      contexts_total: contexts.length,
      mentions,
      contexts,
      rawPayload: entry,
    };
  }

  function normalizeFallbackReferences(data, fallbackMentions, mentionsByRefId, contextsByRefId) {
    const references = Array.isArray(data?.references) ? data.references : [];
    if (references.length) {
      return references.map((entry, index) => {
        const fallbackIndex = normalizeNumber(entry?.index) || index + 1;
        const refId = String(entry?.ref_id || entry?.id || `ref-${fallbackIndex}`).trim();
        return normalizeVisualReference(
          {
            ...entry,
            ref_id: refId,
            text: entry?.text || entry?.raw || entry?.citation || '',
            page: normalizePageValue(entry?.display_page, { oneBased: true }) ?? entry?.page,
          },
          index,
          mentionsByRefId,
          contextsByRefId
        );
      });
    }

    const seen = new Set();
    const rows = [];
    fallbackMentions.forEach((mention, index) => {
      const refId = String(mention?.ref_id || `result-${index + 1}`);
      if (seen.has(refId)) return;
      seen.add(refId);
      const parsedIndex = parseRefIndex(refId);
      rows.push(
        normalizeVisualReference(
          {
            ref_id: refId,
            index: parsedIndex || rows.length + 1,
            text: mention?.text || `Referencia ${parsedIndex || rows.length + 1}`,
            title: parsedIndex ? `Referencia [${parsedIndex}]` : 'Referencia detectada',
            page: mention?.page,
          },
          rows.length,
          mentionsByRefId,
          contextsByRefId
        )
      );
    });
    return rows;
  }

  function normalizeReferenceRows(data) {
    const referencesData =
      data?.references_data && typeof data.references_data === 'object'
        ? data.references_data
        : {};
    const visualReferences = Array.isArray(referencesData.references)
      ? referencesData.references
      : [];
    const visualCitations = Array.isArray(referencesData.citations)
      ? referencesData.citations
      : [];
    const visualContexts = Array.isArray(referencesData.contexts)
      ? referencesData.contexts
      : [];
    const fallbackMentions = Array.isArray(data?.results)
      ? data.results.map(buildMentionFromResult)
      : [];
    const mentions = visualCitations.length ? visualCitations : fallbackMentions;
    const contexts = visualContexts;
    const mentionsByRefId = groupByRefId(mentions);
    const contextsByRefId = groupByRefId(contexts);
    const rows = visualReferences.length
      ? visualReferences.map((entry, index) =>
          normalizeVisualReference(entry, index, mentionsByRefId, contextsByRefId)
        )
      : normalizeFallbackReferences(data, fallbackMentions, mentionsByRefId, contextsByRefId);
    rows.sort((a, b) => (a.index || 0) - (b.index || 0));

    return {
      rows,
      references_total: rows.length,
      citations_total: mentions.length,
      contexts_total: contexts.length,
      engine_used: data?.engine_used || data?.stats?.engine_used || '',
      source: visualReferences.length ? 'references_data' : 'fallback',
    };
  }

  function rowMatchesQuery(row, query) {
    if (!query) return true;
    const haystack = [
      row.text,
      row.title,
      row.author,
      row.doi,
      ...(row.mentions || []).map((mention) => mention?.text || ''),
    ]
      .join(' ')
      .toLowerCase();
    return haystack.includes(query);
  }

  function getReferencePanelNotice(model) {
    if (!model || !model.rows.length) {
      return {
        tone: 'warning',
        text: 'No se detectaron referencias. Prueba con otro PDF o revisa la calidad del texto extraible.',
      };
    }
    if (!model.citations_total) {
      return {
        tone: 'warning',
        text: 'Se detectaron referencias, pero no citas enlazables en el cuerpo del documento.',
      };
    }
    return {
      tone: 'success',
      text: 'Extraccion completada. Se detectaron referencias enlazables en el cuerpo del documento.',
    };
  }

  function mentionKey(refId, mentionIndex) {
    return `${refId}:${mentionIndex}`;
  }

  function renderReferenceMentionHTML(mention, mentionIndex, refId, expandedMentionKey) {
    const key = mentionKey(refId, mentionIndex);
    const mentionText = compactText(mention?.text) || 'Cita sin texto disponible.';
    const paragraphText = compactText(mention?.paragraph) || mentionText;
    const isExpanded = key === expandedMentionKey;
    const displayText = isExpanded ? paragraphText : mentionText;
    const metaLabel = isExpanded
      ? `${formatDisplayPage(mention?.page)} | parrafo`
      : formatDisplayPage(mention?.page);
    return `
      <button
        type="button"
        class="extract-ref-mention${isExpanded ? ' is-expanded' : ''}"
        data-action="toggle-mention"
        data-ref-id="${escapeAttr(refId)}"
        data-mention-index="${mentionIndex}"
        data-mention-key="${escapeAttr(key)}"
        aria-expanded="${isExpanded ? 'true' : 'false'}"
      >
        <span class="extract-ref-mention-meta">${escapeHTML(metaLabel)}</span>
        <span class="extract-ref-mention-text">${escapeHTML(displayText)}</span>
      </button>
    `;
  }

  function renderReferenceMentionsHTML(mentions, refId, expandedMentionKey) {
    const mentionItems = Array.isArray(mentions) ? mentions : [];
    return `
      <div class="extract-ref-mentions">
        <div class="extract-ref-mentions-title">Menciones (${mentionItems.length})</div>
        ${
          mentionItems.length
            ? mentionItems
                .map((mention, index) =>
                  renderReferenceMentionHTML(mention, index, refId, expandedMentionKey)
                )
                .join('')
            : '<div class="extract-ref-no-mentions">Sin menciones detectadas.</div>'
        }
      </div>
    `;
  }

  function renderReferenceRowHTML(row, selectedRefId, expandedMentionKey) {
    const isActive = row.ref_id === selectedRefId;
    const pageLabel = formatDisplayPage(row.page);
    const referenceText = row.text || 'Sin texto de referencia.';
    const title = row.title || 'Sin titulo';
    const mentions = Array.isArray(row.mentions) ? row.mentions : [];
    return `
      <div
        class="extract-ref-row${isActive ? ' is-active' : ''}"
        data-ref-id="${escapeAttr(row.ref_id)}"
      >
        <div class="extract-ref-top">
          <span class="extract-ref-index">#${escapeHTML(row.index || '-')}</span>
          <span class="extract-ref-page">${escapeHTML(pageLabel)} | menciones: ${row.mentions_total || 0}</span>
        </div>
        <div class="${row.text ? 'extract-ref-snippet' : 'extract-ref-snippet is-muted'}">
          "${escapeHTML(referenceText)}"
        </div>
        <div class="extract-ref-footer">
          <div class="extract-ref-footer-main">
            <span class="extract-ref-title">${escapeHTML(title)}</span>
            ${row.author ? `<span class="extract-ref-author"> - ${escapeHTML(row.author)}</span>` : ''}
          </div>
          ${row.structure_source ? `<div class="extract-ref-meta">structure_source: ${escapeHTML(row.structure_source)}</div>` : ''}
          ${row.doi ? `<div class="extract-ref-doi">DOI: ${escapeHTML(row.doi)}</div>` : ''}
        </div>
        ${renderReferenceMentionsHTML(mentions, row.ref_id, expandedMentionKey)}
      </div>
    `;
  }

  function renderReferencePanelHTML(model, query = '', selectedRefId = '', expandedMentionKey = '') {
    const safeModel = model || {
      rows: [],
      references_total: 0,
      citations_total: 0,
      contexts_total: 0,
      engine_used: '',
    };
    const normalizedQuery = compactText(query).toLowerCase();
    const filteredRows = (safeModel.rows || []).filter((row) =>
      rowMatchesQuery(row, normalizedQuery)
    );
    const activeRefId =
      selectedRefId && filteredRows.some((row) => row.ref_id === selectedRefId)
        ? selectedRefId
        : (filteredRows[0]?.ref_id || '');
    const notice = getReferencePanelNotice(safeModel);
    const engineLabel = safeModel.engine_used || '-';
    const rowsHTML = !safeModel.rows.length
      ? '<div class="extract-ref-empty">No hay referencias disponibles para mostrar.</div>'
      : !filteredRows.length
        ? '<div class="extract-ref-empty">No hay referencias que coincidan con la busqueda.</div>'
        : filteredRows
            .map((row) => renderReferenceRowHTML(row, activeRefId, expandedMentionKey))
            .join('');

    return `
      <div class="extract-ref-panel" data-selected-ref-id="${escapeAttr(activeRefId)}">
        <div class="extract-ref-header">
          <div>
            <div class="extract-ref-title-main">Referencias extraidas</div>
            <div class="extract-ref-muted">motor: ${escapeHTML(engineLabel)}</div>
          </div>
          <div class="extract-ref-muted">${safeModel.references_total || 0} total</div>
        </div>
        <div class="extract-ref-metrics">
          <span class="extract-ref-pill">Refs: ${safeModel.references_total || 0}</span>
          <span class="extract-ref-pill">Citas: ${safeModel.citations_total || 0}</span>
          <span class="extract-ref-pill">Contextos: ${safeModel.contexts_total || 0}</span>
        </div>
        <div class="extract-ref-status is-${escapeAttr(notice.tone)}">${escapeHTML(notice.text)}</div>
        <label class="visually-hidden" for="extract-reference-search">Buscar referencias</label>
        <input
          id="extract-reference-search"
          class="form-control extract-ref-search"
          type="search"
          value="${escapeAttr(query)}"
          data-action="filter-references"
          placeholder="Buscar referencias"
        >
        <div class="extract-ref-list">${rowsHTML}</div>
      </div>
    `;
  }

  function rerenderReferencePanel({ preserveSearch = false } = {}) {
    if (!resultsBox || !referencesPanelState.model) return;
    resultsBox.innerHTML = renderReferencePanelHTML(
      referencesPanelState.model,
      referencesPanelState.query,
      referencesPanelState.selectedRefId,
      referencesPanelState.expandedMentionKey
    );
    const selectedFromMarkup = resultsBox
      .querySelector('.extract-ref-panel')
      ?.dataset.selectedRefId;
    referencesPanelState.selectedRefId = selectedFromMarkup || '';
    if (preserveSearch) {
      const searchInput = resultsBox.querySelector('[data-action="filter-references"]');
      if (searchInput) {
        searchInput.focus();
        const cursor = searchInput.value.length;
        searchInput.setSelectionRange?.(cursor, cursor);
      }
    }
  }

  function cardHTML(item) {
    const header    = `Ref [${item.ref}] · Fragmento ${item.idx}`;
    const snippet   = escapeHTML(item.snippet || '');
    const paragraph = escapeHTML(item.paragraph || '');
    return `
      <div class="ce-card border rounded p-2 mb-2">
        <div class="fw-semibold mb-1">${header}</div>
        <div class="ce-snippet">${snippet}</div>

        <div class="mt-2 d-flex flex-wrap gap-2">
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-snippet">Copiar fragmento</button>
          <button class="btn btn-outline-secondary btn-sm" data-action="copy-paragraph">Copiar párrafo</button>
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

  function renderLegacyResults(data) {
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
      // Conserva el payload crudo para compatibilidad del bloque legacy.
      wrap.firstElementChild.dataset.payload = JSON.stringify(item.raw ?? item);
      frag.appendChild(wrap.firstElementChild);
    });
    resultsBox.appendChild(frag);

    summaryBox.textContent = `${list.length} citas detectadas · motor: ${data.engine_used || '—'}`;
    summaryBox.classList.remove('d-none');
    resultsBox.classList.remove('d-none');
  }

  function wireLegacyCardActions() {
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

  function renderResults(data) {
    const model = normalizeReferenceRows(data);
    referencesPanelState = {
      model,
      query: '',
      selectedRefId: model.rows[0]?.ref_id || '',
      expandedMentionKey: '',
    };
    rerenderReferencePanel();

    summaryBox.textContent = `${model.references_total} referencias - ${model.citations_total} citas - motor: ${data.engine_used || '-'}`;
    summaryBox.classList.remove('d-none');
    resultsBox.classList.remove('d-none');
  }

  function wireCardActions() {
    if (!resultsBox || resultsActionsWired) return;
    resultsActionsWired = true;

    resultsBox.addEventListener('input', (ev) => {
      const el = ev.target.closest('[data-action="filter-references"]');
      if (!el) return;
      referencesPanelState.query = el.value || '';
      rerenderReferencePanel({ preserveSearch: true });
    });

    resultsBox.addEventListener('click', (ev) => {
      const el = ev.target.closest('button');
      if (!el) return;

      const action = el.dataset.action;
      const refId = el.dataset.refId || el.closest('[data-ref-id]')?.dataset.refId || '';

      if (action === 'toggle-mention') {
        const key = el.dataset.mentionKey || mentionKey(refId, Number(el.dataset.mentionIndex) || 0);
        referencesPanelState.selectedRefId = refId;
        referencesPanelState.expandedMentionKey =
          referencesPanelState.expandedMentionKey === key ? '' : key;
        rerenderReferencePanel();
      }
    });
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
      enrichment: extractionResult?.enrichment || null,
      articleInfo: extractionResult?.articleInfo || null,
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
      resetProgress();
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
    btnSubmit.textContent = 'Extrayendo... 0%';
    startProgress();

    try {
      const fd = new FormData();
      fd.append('manuscript', file);
      fd.append('engine', engineSel.value);
      const debugRequested = debugEnabled && Boolean(debugChk?.checked);
      fd.append('debug', debugRequested ? '1' : '0');
      fd.append('debug_reference_detection', debugRequested ? '1' : '0');

      const res  = await fetch(ENDPOINT, { method: 'POST', body: fd });
      const data = await res.json();

      // --- Manejo de error del servidor (ok:false) ---
      if (!data.ok) {
        resetProgress();
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
      completeProgress();
      if (debugEnabled && data.reference_debug?.output_path) {
        summaryBox.textContent = `${summaryBox.textContent} · debug: ${data.reference_debug.output_path}`;
      }
      enableDebugDownload(data.reference_debug);

      if (data.trace) {
        tracePre.textContent = JSON.stringify(data.trace, null, 2);
        tracePre.classList.remove('d-none');
      }

      wireCardActions();
    } catch (e) {
      resetProgress();
      alertBox.textContent = 'Error de red o de servidor al extraer citas.';
      alertBox.classList.remove('d-none');
    } finally {
      btnSubmit.textContent = originalText;
      syncButton();
    }
  });
})();
