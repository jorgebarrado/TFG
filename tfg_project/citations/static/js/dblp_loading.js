(function () {
  const LABELS = [
    { at: 10, text: 'Validando URL de DBLP...' },
    { at: 25, text: 'Consultando el perfil del autor...' },
    { at: 45, text: 'Recuperando publicaciones desde DBLP...' },
    { at: 62, text: 'Preparando articulos y metadatos...' },
    { at: 78, text: 'Consultando citas en Semantic Scholar...' },
    { at: 88, text: 'Cargando resultados...' },
  ];

  function updateProgress(progress, value, labels) {
    const safeValue = Math.max(0, Math.min(92, Math.round(value)));
    const bar = progress.querySelector('[data-dblp-progress-bar]');
    const valueEl = progress.querySelector('[data-dblp-progress-value]');
    const labelEl = progress.querySelector('[data-dblp-progress-label]');
    const activeLabels = labels || LABELS;

    if (bar) {
      bar.style.width = `${safeValue}%`;
    }
    if (valueEl) {
      valueEl.textContent = `${safeValue}%`;
    }
    if (labelEl) {
      let label = null;
      for (let index = activeLabels.length - 1; index >= 0; index -= 1) {
        if (safeValue >= activeLabels[index].at) {
          label = activeLabels[index];
          break;
        }
      }
      if (label) {
        labelEl.textContent = label.text;
      }
    }
  }

  function startProgress(progress, options) {
    const labels = options?.labels || LABELS;
    const startedAt = Date.now();
    let value = 6;
    updateProgress(progress, value, labels);
    return window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const easedTarget = 8 + (84 * (1 - Math.exp(-elapsed / 55000)));
      value = Math.max(value + 0.25, Math.min(92, easedTarget));
      updateProgress(progress, value, labels);
    }, 900);
  }

  function configureProgressForForm(progress, form) {
    const metaEl = progress.querySelector('[data-dblp-progress-meta]');
    const includeWithoutCitations = form
      .querySelector('input[type="checkbox"][name="include_without_citations"]')
      ?.checked;

    if (metaEl && includeWithoutCitations === false) {
      metaEl.textContent = 'Consultando DBLP y Semantic Scholar para descartar articulos sin citas. Este paso puede tardar en perfiles largos.';
    }
  }

  function initDBLPLoadForm(form) {
    const progress = document.querySelector('[data-dblp-loading-progress]');
    if (!progress) return;

    form.addEventListener('submit', () => {
      if (form.dataset.dblpLoading === '1') return;
      form.dataset.dblpLoading = '1';
      configureProgressForForm(progress, form);
      progress.classList.remove('d-none');
      progress.scrollIntoView({ behavior: 'smooth', block: 'center' });

      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.dataset.originalText = submitButton.textContent;
        submitButton.textContent = 'Buscando...';
      }

      startProgress(progress);
    });
  }

  function initDBLPLoadMoreLink(link) {
    const progress = document.querySelector('[data-dblp-loading-progress]');
    if (!progress) return;

    link.addEventListener('click', (event) => {
      if (link.dataset.dblpLoading === '1') {
        event.preventDefault();
        return;
      }

      event.preventDefault();
      link.dataset.dblpLoading = '1';
      link.classList.add('disabled');
      link.setAttribute('aria-disabled', 'true');
      link.dataset.originalText = link.textContent;
      link.textContent = 'Cargando...';

      progress.classList.remove('d-none');
      progress.scrollIntoView({ behavior: 'smooth', block: 'center' });
      startProgress(progress);

      // Deja que el navegador pinte el spinner antes de navegar.
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          window.location.href = link.href;
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-dblp-load-form]').forEach(initDBLPLoadForm);
    document.querySelectorAll('[data-dblp-load-more]').forEach(initDBLPLoadMoreLink);
  });
})();
