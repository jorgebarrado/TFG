// -------------------------------------------------------------
// citation_extractor.js
// EN/ES: Uploads manuscript (PDF or TXT) and displays results
// in a clean, interactive format with highlights and cards.
// -------------------------------------------------------------

console.log("citation_extractor.js LOADED");
window.uploadAndExtract = uploadAndExtract;

// Helper: Normalize extracted text (remove line breaks, fix hyphens)
function normalizeText(s) {
  if (!s) return "";
  s = s.replace(/(\w)-\s*\n\s*(\w)/g, "$1$2"); // join broken words
  s = s.replace(/\s*\n+\s*/g, " "); // remove newlines
  s = s.replace(/\s{2,}/g, " "); // collapse spaces
  return s.trim();
}

// Helper: Highlight a snippet inside text
function highlightOnce(text, start, end) {
  if (typeof start !== "number" || typeof end !== "number") return text;
  const before = text.slice(0, start);
  const mid = text.slice(start, end);
  const after = text.slice(end);
  return `${before}<mark>${mid}</mark>${after}`;
}

// Render extracted citations as cards
function renderResults(data) {
  const panel = document.getElementById("results-panel");
  panel.innerHTML = "";

  if (!data || Object.keys(data).length === 0) {
    panel.innerHTML = `
      <div class="alert alert-warning">
        No se han encontrado citas reconocibles en el documento.<br>
        It was not possible to detect recognizable citations in this file.
      </div>`;
    return;
  }

  // Count total matches
  let total = 0;
  Object.values(data).forEach(list => (total += (list?.length || 0)));

  const header = document.createElement("div");
  header.className = "alert alert-info";
  header.textContent = `Citas detectadas / Citations found: ${total}`;
  panel.appendChild(header);

  // For each citation group ([1], [2], (Smith, 2020), etc.)
  for (const [key, items] of Object.entries(data)) {
    const card = document.createElement("div");
    card.className = "card mb-3 shadow-sm";

    const body = document.createElement("div");
    body.className = "card-body";

    const title = document.createElement("h5");
    title.className = "card-title";
    title.textContent = key;
    body.appendChild(title);

    (items || []).forEach((it, idx) => {
      const paraClean = normalizeText(it.paragraph || "");
      const snippetClean = normalizeText(it.snippet || "");

      // Highlight if possible
      let htmlSnippet = snippetClean;
      if (typeof it.start === "number" && typeof it.end === "number") {
        htmlSnippet = highlightOnce(paraClean, it.start, it.end);
      }

      // Snippet visible
      const pSnippet = document.createElement("p");
      pSnippet.className = "mb-2";
      pSnippet.innerHTML = htmlSnippet;

      // Collapsible full paragraph
      const details = document.createElement("details");
      details.className = "mt-1";
      const summary = document.createElement("summary");
      summary.textContent = `Ver párrafo completo / View full paragraph (${idx + 1})`;
      const pFull = document.createElement("p");
      pFull.className = "mt-2 mb-0";
      pFull.textContent = paraClean;
      details.appendChild(summary);
      details.appendChild(pFull);

      body.appendChild(pSnippet);
      body.appendChild(details);

      if (idx < items.length - 1) {
        const hr = document.createElement("hr");
        body.appendChild(hr);
      }
    });

    card.appendChild(body);
    panel.appendChild(card);
  }
}

// Upload and process file
async function uploadAndExtract(urlName) {
  const fileInput = document.getElementById("manuscript");
  const panel = document.getElementById("results-panel");
  panel.innerHTML = '<div class="alert alert-secondary">Procesando... / Processing...</div>';

  if (!fileInput.files[0]) {
    panel.innerHTML = `
      <div class="alert alert-warning">
        Selecciona un archivo antes de continuar.<br>
        Please choose a file before continuing.
      </div>`;
    return;
  }

  const fd = new FormData();
  fd.append("manuscript", fileInput.files[0]);

  try {
    const res = await fetch(urlName, { method: "POST", body: fd });
    const text = await res.text();

    try {
      const data = JSON.parse(text);
      renderResults(data);
    } catch (parseErr) {
      panel.innerHTML = `
        <div class="alert alert-danger">
          Error al interpretar la respuesta del servidor.<br>
          Could not parse server response (${res.status}).<br>
          <pre class="mt-2 mb-0" style="white-space:pre-wrap">${text}</pre>
        </div>`;
    }
  } catch (err) {
    panel.innerHTML = `
      <div class="alert alert-danger">
        Error de red: ${err.message || err}.<br>
        Network error while sending the file.
      </div>`;
  }
}
