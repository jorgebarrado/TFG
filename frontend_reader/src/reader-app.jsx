import React, { useEffect, useMemo, useRef, useState } from "react";
import pdfComponents from "@allenai/pdf-components";
import "@allenai/pdf-components/dist/pdf-components.css";
import "react-pdf/dist/esm/Page/AnnotationLayer.css";
import "react-pdf/dist/esm/Page/TextLayer.css";

const {
  ContextProvider,
  DocumentContext,
  DocumentWrapper,
  PageWrapper,
  RENDER_TYPE,
  scrollToPdfPageIndex,
} = pdfComponents;

const SNIPPET_FILTERS = [
  { key: "all", label: "All" },
  { key: "bracket", label: "Bracket" },
  { key: "authoryear", label: "Author-year" },
  { key: "doi", label: "DOI" },
];

const REFERENCE_FILTERS = [
  { key: "all", label: "All" },
  { key: "has_doi", label: "With DOI" },
  { key: "no_doi", label: "No DOI" },
];

const DOI_REGEX = /10\.\d{4,9}\/[-._;()/:A-Za-z0-9]+/i;
const DOI_URL_REGEX = /https?:\/\/(?:dx\.)?doi\.org\/([^\s]+)/i;
const BRACKET_REGEX = /\[(\d+)\]/;
const INLINE_CITATION_REGEX = /\[(\d+(?:\s*[,;]\s*\d+|\s*[-–—]\s*\d+)*)\]/g;

const MAX_CITATION_RANGE = 50;

function normalizeDoi(value) {
  if (!value) return "";
  let doi = String(value).trim();
  doi = doi.replace(/^doi:\s*/i, "");
  doi = doi.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "");
  doi = doi.replace(/[).,;:\]]+$/, "");
  return doi.trim().toLowerCase();
}

function extractDoi(text) {
  if (!text) return "";
  const urlMatch = DOI_URL_REGEX.exec(text);
  if (urlMatch) {
    return normalizeDoi(urlMatch[1]);
  }
  const match = DOI_REGEX.exec(text);
  if (match) {
    return normalizeDoi(match[0]);
  }
  return "";
}

function extractBracketIndex(text) {
  if (!text) return null;
  const match = BRACKET_REGEX.exec(text);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

function normalizeSnippetType(value) {
  const t = String(value || "").toLowerCase();
  if (t === "numeric" || t === "bracket") return "bracket";
  if (t === "author-year" || t === "authoryear" || t === "author_year") {
    return "authoryear";
  }
  if (t === "doi") return "doi";
  return "bracket";
}

function normalizeSnippet(raw, index) {
  if (!raw) return null;
  const pageValue = Number(raw.page);
  const page = Number.isFinite(pageValue) && pageValue > 0 ? pageValue : null;
  const snippet = raw.snippet || raw.text || raw.context || "";
  if (!snippet) return null;
  return {
    id: raw.id || `snippet-${index + 1}`,
    page,
    snippet,
    type: normalizeSnippetType(raw.type || raw.kind || raw.pattern),
    confidence: Number(raw.confidence || 0),
  };
}

function normalizeReference(raw, index) {
  if (!raw) return null;
  const rawText =
    typeof raw === "string"
      ? raw
      : raw.raw || raw.text || raw.reference || "";
  const cleanedRaw = String(rawText || "").trim();
  if (!cleanedRaw) return null;
  const idxValue = Number(raw.index);
  const refIndex = Number.isFinite(idxValue) && idxValue > 0 ? idxValue : index + 1;
  const doi = normalizeDoi(raw.doi || extractDoi(cleanedRaw));
  return {
    id: raw.id || `ref-${refIndex}-${doi || index}`,
    index: refIndex,
    raw: cleanedRaw,
    doi,
    doi_source: raw.doi_source || (doi ? "regex" : null),
    confidence: Number(raw.confidence || (doi ? 1.0 : 0.5)),
    numbered: Boolean(raw.numbered),
  };
}

function referenceKey(ref) {
  if (!ref) return "";
  return ref.doi ? `doi:${ref.doi}` : `idx:${ref.index}`;
}

function parseCitationNumbers(raw) {
  if (!raw) return [];
  const cleaned = String(raw).replace(/^\[|\]$/g, "");
  const parts = cleaned.split(/[;,]/);
  const numbers = [];
  parts.forEach((part) => {
    const token = part.replace(/[–—]/g, "-").trim();
    if (!token) return;
    if (token.includes("-")) {
      const [startRaw, endRaw] = token.split("-").map((value) => value.trim());
      const start = Number(startRaw);
      const end = Number(endRaw);
      if (!Number.isFinite(start) || !Number.isFinite(end)) {
        return;
      }
      const step = start <= end ? 1 : -1;
      const span = Math.min(Math.abs(end - start) + 1, MAX_CITATION_RANGE);
      for (let i = 0; i < span; i += 1) {
        numbers.push(start + i * step);
      }
      return;
    }
    const value = Number(token);
    if (Number.isFinite(value)) {
      numbers.push(value);
    }
  });
  return Array.from(new Set(numbers));
}

function buildTextLayerIndex(textLayer) {
  const spans = Array.from(textLayer.querySelectorAll("span"));
  const nodes = [];
  let text = "";
  spans.forEach((span) => {
    const content = span.textContent || "";
    if (!content) return;
    const start = text.length;
    text += content;
    const end = text.length;
    const node = span.firstChild || span;
    nodes.push({ node, start, end });
  });
  return { text, nodes };
}

function findNodeAtOffset(nodes, offset) {
  for (let i = 0; i < nodes.length; i += 1) {
    const item = nodes[i];
    if (offset >= item.start && offset <= item.end) {
      return item;
    }
  }
  return null;
}

function collectCitationHitsForPage(pageEl) {
  if (!pageEl) return [];
  const textLayer = pageEl.querySelector(".textLayer");
  if (!textLayer) return [];
  const { text, nodes } = buildTextLayerIndex(textLayer);
  if (!text) return [];

  const pageNumber = Number(pageEl.dataset.pageNumber || pageEl.getAttribute("data-page-number"));
  const pageRect = pageEl.getBoundingClientRect();
  const hits = [];
  const regex = new RegExp(INLINE_CITATION_REGEX.source, "g");

  let match = regex.exec(text);
  while (match) {
    const startOffset = match.index;
    const endOffset = startOffset + match[0].length;
    const startNode = findNodeAtOffset(nodes, startOffset);
    const endNode = findNodeAtOffset(nodes, endOffset);
    if (startNode && endNode) {
      const range = document.createRange();
      range.setStart(startNode.node, Math.max(0, startOffset - startNode.start));
      range.setEnd(endNode.node, Math.max(0, endOffset - endNode.start));

      const rects = Array.from(range.getClientRects())
        .filter((rect) => rect.width > 1 && rect.height > 1)
        .map((rect) => ({
          left: rect.left - pageRect.left,
          top: rect.top - pageRect.top,
          width: rect.width,
          height: rect.height,
        }));

      if (rects.length) {
        hits.push({
          id: `cite-${pageNumber}-${startOffset}`,
          page: Number.isFinite(pageNumber) ? pageNumber : null,
          label: match[0],
          numbers: parseCitationNumbers(match[0]),
          rects,
          anchorRect: rects[0],
        });
      }
    }
    match = regex.exec(text);
  }
  return hits;
}

function useHighlightedSnippet(mention, onHighlight) {
  const lastTokenRef = useRef("");

  useEffect(() => {
    const pageNumber = Number(mention?.page);
    if (!mention || !Number.isFinite(pageNumber) || !mention.snippet) {
      return;
    }

    const token = `${pageNumber}-${mention.snippet.slice(0, 64)}`;
    if (lastTokenRef.current === token) {
      return;
    }
    lastTokenRef.current = token;

    const run = () => {
      document
        .querySelectorAll(".reader-highlight")
        .forEach((el) => el.classList.remove("reader-highlight"));

      const pageEl = document.querySelector(
        `.pdf-reader__page[data-page-number="${pageNumber}"]`
      );
      if (!pageEl) {
        return;
      }
      const textLayer = pageEl.querySelector(".textLayer");
      if (!textLayer) {
        return;
      }

      const normalized = String(mention.snippet)
        .toLowerCase()
        .replace(/\s+/g, " ")
        .trim();
      if (!normalized) {
        return;
      }
      const keywords = normalized
        .split(" ")
        .filter((word) => word.length > 3)
        .slice(0, 8);

      let matched = false;
      const spans = textLayer.querySelectorAll("span");
      spans.forEach((span) => {
        const text = (span.textContent || "").toLowerCase();
        if (keywords.some((word) => text.includes(word))) {
          matched = true;
          span.classList.add("reader-highlight");
        }
      });
      if (typeof onHighlight === "function") {
        onHighlight(matched);
      }
    };

    const timer = setTimeout(run, 350);
    return () => clearTimeout(timer);
  }, [mention, onHighlight]);
}

function PdfPages() {
  const { numPages } = React.useContext(DocumentContext);
  if (!numPages) {
    return <div className="reader-loading">Loading PDF...</div>;
  }
  return (
    <div className="reader-pages">
      {Array.from({ length: numPages }).map((_, index) => (
        <PageWrapper
          key={index}
          pageIndex={index}
          renderType={RENDER_TYPE.MULTI_CANVAS}
        />
      ))}
    </div>
  );
}

function PdfViewer({ pdfUrl, selectedMention, onHighlight, viewerRef }) {
  useHighlightedSnippet(selectedMention, onHighlight);

  if (!pdfUrl) {
    return <div className="reader-empty">No hay PDF disponible.</div>;
  }

  return (
    <div className="reader-viewer" ref={viewerRef}>
      <ContextProvider>
        <DocumentWrapper file={pdfUrl} renderType={RENDER_TYPE.MULTI_CANVAS}>
          <PdfPages />
        </DocumentWrapper>
      </ContextProvider>
    </div>
  );
}

export default function ReaderApp({
  apiUrl,
  pdfUrl,
  reportId,
  previewFile,
  previewSnippets = [],
  previewStats = null,
  previewReferences = [],
}) {
  const [loading, setLoading] = useState(Boolean(apiUrl));
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [snippetsData, setSnippetsData] = useState(
    Array.isArray(previewSnippets) ? previewSnippets : []
  );
  const [referencesData, setReferencesData] = useState(
    Array.isArray(previewReferences) ? previewReferences : []
  );
  const [stats, setStats] = useState(previewStats || null);
  const [activeTab, setActiveTab] = useState("snippets");
  const [snippetQuery, setSnippetQuery] = useState("");
  const [referenceQuery, setReferenceQuery] = useState("");
  const [snippetFilter, setSnippetFilter] = useState("all");
  const [referenceFilter, setReferenceFilter] = useState("all");
  const [selectedSnippet, setSelectedSnippet] = useState(null);
  const [highlightNotice, setHighlightNotice] = useState("");
  const [activeReferenceKey, setActiveReferenceKey] = useState("");
  const [expandedReferences, setExpandedReferences] = useState([]);
  const [activeCitation, setActiveCitation] = useState(null);
  const [citationPopoverStyle, setCitationPopoverStyle] = useState(null);

  const viewerRef = useRef(null);
  const viewerShellRef = useRef(null);
  const referenceElements = useRef(new Map());
  const citationHitMapRef = useRef(new Map());
  const activeCitationRef = useRef(null);

  useEffect(() => {
    if (!previewFile) {
      return;
    }
    const objectUrl = URL.createObjectURL(previewFile);
    setPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [previewFile]);

  useEffect(() => {
    if (Array.isArray(previewSnippets)) {
      setSnippetsData(previewSnippets);
    }
  }, [previewSnippets]);

  useEffect(() => {
    if (Array.isArray(previewReferences)) {
      setReferencesData(previewReferences);
    }
  }, [previewReferences]);

  useEffect(() => {
    setStats(previewStats || null);
  }, [previewStats]);

  useEffect(() => {
    const handler = (event) => {
      const file = event.detail?.file;
      if (!file) return;
      const objectUrl = URL.createObjectURL(file);
      setPreviewUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current);
        }
        return objectUrl;
      });
    };
    window.addEventListener("reader:file-ready", handler);
    return () => window.removeEventListener("reader:file-ready", handler);
  }, []);

  useEffect(() => {
    const handler = (event) => {
      const nextSnippets = Array.isArray(event.detail?.snippets)
        ? event.detail.snippets
        : [];
      const nextReferences = Array.isArray(event.detail?.references)
        ? event.detail.references
        : [];
      const nextStats = event.detail?.stats || null;
      setSnippetsData(nextSnippets);
      setReferencesData(nextReferences);
      setStats(nextStats);
    };
    window.addEventListener("reader:data", handler);
    return () => window.removeEventListener("reader:data", handler);
  }, []);

  useEffect(() => {
    if (!apiUrl) {
      setLoading(false);
      return;
    }
    let active = true;

    setLoading(true);
    fetch(apiUrl, { method: "GET" })
      .then((res) => res.json())
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setError("Failed to load reader data.");
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [apiUrl]);

  useEffect(() => {
    setSelectedSnippet(null);
    setHighlightNotice("");
  }, [snippetsData]);

  useEffect(() => {
    activeCitationRef.current = activeCitation;
  }, [activeCitation]);

  useEffect(() => {
    const handler = (event) => {
      if (event.key === "Escape") {
        setActiveCitation(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const apiSnippetsSource =
    (Array.isArray(data?.snippets) && data.snippets) ||
    (Array.isArray(data?.mentions) && data.mentions) ||
    [];
  const apiReferencesSource =
    (Array.isArray(data?.references) && data.references) || [];

  const activeSnippetsSource =
    snippetsData.length > 0 ? snippetsData : apiSnippetsSource;
  const activeReferencesSource =
    referencesData.length > 0 ? referencesData : apiReferencesSource;

  const normalizedSnippets = useMemo(
    () =>
      activeSnippetsSource
        .map((item, index) => normalizeSnippet(item, index))
        .filter(Boolean),
    [activeSnippetsSource]
  );

  const normalizedReferences = useMemo(
    () =>
      activeReferencesSource
        .map((item, index) => normalizeReference(item, index))
        .filter(Boolean),
    [activeReferencesSource]
  );

  const effectiveStats = useMemo(() => {
    const base = stats || data?.stats || {};
    const doisTotal = normalizedReferences.filter((ref) => ref.doi).length;
    return {
      pages_total: base.pages_total || 0,
      snippets_total:
        typeof base.snippets_total === "number"
          ? base.snippets_total
          : normalizedSnippets.length,
      references_total:
        typeof base.references_total === "number"
          ? base.references_total
          : normalizedReferences.length,
      dois_total:
        typeof base.dois_total === "number" ? base.dois_total : doisTotal,
      engine_used: base.engine_used || "",
      time_ms: base.time_ms ?? null,
      references_numbered: Boolean(base.references_numbered),
    };
  }, [stats, data, normalizedSnippets, normalizedReferences]);

  const referencesNumbered =
    effectiveStats.references_numbered ||
    normalizedReferences.some((ref) => ref.numbered);

  const referenceByDoi = useMemo(() => {
    const map = new Map();
    normalizedReferences.forEach((ref) => {
      if (ref.doi && !map.has(ref.doi)) {
        map.set(ref.doi, ref);
      }
    });
    return map;
  }, [normalizedReferences]);

  const referenceByIndex = useMemo(() => {
    const map = new Map();
    normalizedReferences.forEach((ref) => {
      if (!map.has(ref.index)) {
        map.set(ref.index, ref);
      }
    });
    return map;
  }, [normalizedReferences]);

  const derivedSnippets = useMemo(() => {
    return normalizedSnippets.map((snippet) => {
      const doi = extractDoi(snippet.snippet);
      const bracketIndex = extractBracketIndex(snippet.snippet);
      return {
        ...snippet,
        doi_in_snippet: doi,
        bracket_index: bracketIndex,
      };
    });
  }, [normalizedSnippets]);

  const filteredSnippets = useMemo(() => {
    const query = snippetQuery.trim().toLowerCase();
    return derivedSnippets.filter((item) => {
      if (snippetFilter !== "all" && item.type !== snippetFilter) {
        return false;
      }
      if (!query) return true;
      return item.snippet.toLowerCase().includes(query);
    });
  }, [derivedSnippets, snippetQuery, snippetFilter]);

  const filteredReferences = useMemo(() => {
    const query = referenceQuery.trim().toLowerCase();
    return normalizedReferences.filter((ref) => {
      if (referenceFilter === "has_doi" && !ref.doi) return false;
      if (referenceFilter === "no_doi" && ref.doi) return false;
      if (!query) return true;
      return (
        ref.raw.toLowerCase().includes(query) ||
        (ref.doi && ref.doi.includes(query))
      );
    });
  }, [normalizedReferences, referenceFilter, referenceQuery]);

  const resolvedPdfUrl = previewUrl || data?.pdf_url || pdfUrl || "";
  const linkedReferences = useMemo(() => {
    if (!activeCitation || !Array.isArray(activeCitation.numbers)) {
      return [];
    }
    return activeCitation.numbers
      .map((number) => referenceByIndex.get(number))
      .filter(Boolean);
  }, [activeCitation, referenceByIndex]);

  const updateCitationPopoverPosition = () => {
    if (!activeCitation) {
      setCitationPopoverStyle(null);
      return;
    }
    const shellEl = viewerShellRef.current;
    const viewerEl = viewerRef.current;
    if (!shellEl || !viewerEl) return;
    const pageEl = viewerEl.querySelector(
      `.pdf-reader__page[data-page-number="${activeCitation.page}"]`
    );
    if (!pageEl || !activeCitation.anchorRect) return;
    const shellRect = shellEl.getBoundingClientRect();
    const pageRect = pageEl.getBoundingClientRect();
    const top = pageRect.top - shellRect.top + activeCitation.anchorRect.top;
    const left = pageRect.left - shellRect.left + activeCitation.anchorRect.left;
    const maxLeft = Math.max(shellEl.clientWidth - 320, 12);
    setCitationPopoverStyle({
      top: Math.max(12, top - 8),
      left: Math.min(Math.max(12, left), maxLeft),
    });
  };

  useEffect(() => {
    if (!viewerRef.current) return;
    updateCitationPopoverPosition();
  }, [activeCitation]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl) return;
    const onScroll = () => updateCitationPopoverPosition();
    viewerEl.addEventListener("scroll", onScroll);
    return () => viewerEl.removeEventListener("scroll", onScroll);
  }, [activeCitation]);

  useEffect(() => {
    setActiveCitation(null);
  }, [resolvedPdfUrl]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl) return;
    let rafId = null;

    const schedule = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        const newMap = new Map();
        const pages = viewerEl.querySelectorAll(".pdf-reader__page");
        pages.forEach((pageEl) => {
          if (!pageEl) return;
          const hits = collectCitationHitsForPage(pageEl);
          let layer = pageEl.querySelector(".reader-citation-layer");
          if (!layer) {
            layer = document.createElement("div");
            layer.className = "reader-citation-layer";
            if (window.getComputedStyle(pageEl).position === "static") {
              pageEl.style.position = "relative";
            }
            pageEl.appendChild(layer);
          }
          layer.innerHTML = "";
          hits.forEach((hit) => {
            newMap.set(hit.id, hit);
            hit.rects.forEach((rect) => {
              const hitEl = document.createElement("div");
              hitEl.className = "citation-hit";
              hitEl.dataset.citationId = hit.id;
              hitEl.style.left = `${rect.left}px`;
              hitEl.style.top = `${rect.top}px`;
              hitEl.style.width = `${rect.width}px`;
              hitEl.style.height = `${rect.height}px`;
              hitEl.addEventListener("click", (event) => {
                event.stopPropagation();
                const next = newMap.get(hit.id);
                if (next) {
                  setActiveCitation(next);
                }
              });
              layer.appendChild(hitEl);
            });
          });
        });
        citationHitMapRef.current = newMap;
        const currentActive = activeCitationRef.current;
        if (currentActive && !newMap.has(currentActive.id)) {
          setActiveCitation(null);
        }
        updateCitationPopoverPosition();
      });
    };

    const mutationObserver = new MutationObserver(schedule);
    mutationObserver.observe(viewerEl, { childList: true, subtree: true });
    const resizeObserver = new ResizeObserver(schedule);
    resizeObserver.observe(viewerEl);
    window.addEventListener("resize", schedule);
    schedule();

    return () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, [resolvedPdfUrl]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl) return;
    viewerEl
      .querySelectorAll(".citation-hit.is-active")
      .forEach((el) => el.classList.remove("is-active"));
    if (activeCitation?.id) {
      viewerEl
        .querySelectorAll(`[data-citation-id="${activeCitation.id}"]`)
        .forEach((el) => el.classList.add("is-active"));
    }
  }, [activeCitation]);

  const handleSnippetClick = (snippet) => {
    setSelectedSnippet(snippet);
    setHighlightNotice("");
    const pageNumber = Number(snippet?.page);
    if (Number.isFinite(pageNumber)) {
      scrollToPdfPageIndex(pageNumber - 1);
    }
  };

  const handleHighlight = (matched) => {
    if (!selectedSnippet) return;
    if (matched) {
      setHighlightNotice("");
    } else {
      setHighlightNotice("No se encontro el texto exacto; resaltado aproximado.");
    }
  };

  const toggleReferenceRaw = (key) => {
    setExpandedReferences((current) => {
      if (current.includes(key)) {
        return current.filter((entry) => entry !== key);
      }
      return [...current, key];
    });
  };

  const registerReference = (key) => (element) => {
    if (!key) return;
    if (element) {
      referenceElements.current.set(key, element);
    } else {
      referenceElements.current.delete(key);
    }
  };

  const jumpToReference = (refKey) => {
    if (!refKey) return;
    setActiveTab("references");
    setActiveReferenceKey(refKey);
    setTimeout(() => {
      const el = referenceElements.current.get(refKey);
      if (el && el.scrollIntoView) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 150);
  };

  const copyToClipboard = (value) => {
    if (!value) return;
    navigator.clipboard?.writeText(value).catch(() => {});
  };

  const handleViewReference = (ref) => {
    const key = referenceKey(ref);
    if (key) {
      jumpToReference(key);
    }
  };

  return (
    <div className="reader-app">
      <aside className="reader-sidebar">
        <div className="reader-card">
          <div className="reader-card-title">Report</div>
          <div className="reader-card-meta">ID: {reportId || "n/a"}</div>
          <div className="reader-card-meta">
            Snippets: {effectiveStats.snippets_total}
          </div>
          <div className="reader-card-meta">
            References: {effectiveStats.references_total}
          </div>
          <div className="reader-card-meta">DOIs: {effectiveStats.dois_total}</div>
          {effectiveStats.engine_used && (
            <div className="reader-card-meta">
              Engine: {effectiveStats.engine_used}
            </div>
          )}
          {Number.isFinite(Number(effectiveStats.time_ms)) && (
            <div className="reader-card-meta">
              Time: {Number(effectiveStats.time_ms)} ms
            </div>
          )}
          {loading && <div className="reader-muted">Loading data...</div>}
          {error && <div className="reader-error">{error}</div>}
        </div>

        <div className="reader-tabs">
          <button
            type="button"
            className={
              activeTab === "snippets"
                ? "reader-tab is-active"
                : "reader-tab"
            }
            onClick={() => setActiveTab("snippets")}
          >
            Snippets
          </button>
          <button
            type="button"
            className={
              activeTab === "references"
                ? "reader-tab is-active"
                : "reader-tab"
            }
            onClick={() => setActiveTab("references")}
          >
            References
          </button>
          <button
            type="button"
            className={
              activeTab === "stats"
                ? "reader-tab is-active"
                : "reader-tab"
            }
            onClick={() => setActiveTab("stats")}
          >
            Stats
          </button>
        </div>

        {activeTab === "snippets" && (
          <div className="reader-card reader-panel">
            <div className="reader-card-title">Snippets</div>
            <div className="reader-search">
              <input
                type="search"
                value={snippetQuery}
                onChange={(event) => setSnippetQuery(event.target.value)}
                placeholder="Search snippets"
                className="reader-search-input"
              />
            </div>
            <div className="reader-chips">
              {SNIPPET_FILTERS.map((filter) => (
                <button
                  type="button"
                  key={filter.key}
                  className={
                    filter.key === snippetFilter
                      ? "reader-chip is-active"
                      : "reader-chip"
                  }
                  onClick={() => setSnippetFilter(filter.key)}
                >
                  {filter.label}
                </button>
              ))}
            </div>

            {normalizedSnippets.length === 0 ? (
              <div className="reader-muted">
                No snippets yet. Run extraction first.
              </div>
            ) : filteredSnippets.length === 0 ? (
              <div className="reader-muted">No snippets match your filters.</div>
            ) : (
              filteredSnippets.map((snippet) => {
                const linkedByDoi = snippet.doi_in_snippet
                  ? referenceByDoi.get(snippet.doi_in_snippet)
                  : null;
                const linkedByIndex =
                  referencesNumbered && snippet.bracket_index
                    ? referenceByIndex.get(snippet.bracket_index)
                    : null;
                const refKey = referenceKey(linkedByDoi || linkedByIndex);
                return (
                  <div
                    key={snippet.id}
                    className={
                      snippet.id === selectedSnippet?.id
                        ? "reader-mention is-active"
                        : "reader-mention"
                    }
                    role="button"
                    tabIndex={0}
                    onClick={() => handleSnippetClick(snippet)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        handleSnippetClick(snippet);
                      }
                    }}
                  >
                    <div className="reader-mention-snippet">{snippet.snippet}</div>
                    <div className="reader-ref-meta">Page: {snippet.page || "?"}</div>
                    <div className="reader-mention-tags">
                      <span className="reader-badge-inline">{snippet.type}</span>
                      {linkedByDoi && (
                        <span
                          role="button"
                          tabIndex={0}
                          className="reader-link-badge"
                          onClick={(event) => {
                            event.stopPropagation();
                            jumpToReference(refKey);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.stopPropagation();
                              jumpToReference(refKey);
                            }
                          }}
                        >
                          Cites DOI
                        </span>
                      )}
                      {!linkedByDoi && linkedByIndex && (
                        <span
                          role="button"
                          tabIndex={0}
                          className="reader-link-badge"
                          onClick={(event) => {
                            event.stopPropagation();
                            jumpToReference(refKey);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.stopPropagation();
                              jumpToReference(refKey);
                            }
                          }}
                        >
                          Cites [{linkedByIndex.index}]
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === "references" && (
          <div className="reader-card reader-panel">
            <div className="reader-card-title">References</div>
            <div className="reader-search">
              <input
                type="search"
                value={referenceQuery}
                onChange={(event) => setReferenceQuery(event.target.value)}
                placeholder="Search references"
                className="reader-search-input"
              />
            </div>
            <div className="reader-chips">
              {REFERENCE_FILTERS.map((filter) => (
                <button
                  type="button"
                  key={filter.key}
                  className={
                    filter.key === referenceFilter
                      ? "reader-chip is-active"
                      : "reader-chip"
                  }
                  onClick={() => setReferenceFilter(filter.key)}
                >
                  {filter.label}
                </button>
              ))}
            </div>

            {normalizedReferences.length === 0 ? (
              <div className="reader-muted">No references available.</div>
            ) : filteredReferences.length === 0 ? (
              <div className="reader-muted">No references match your filters.</div>
            ) : (
              filteredReferences.map((ref) => {
                const key = referenceKey(ref);
                const expanded = expandedReferences.includes(key);
                return (
                  <div
                    key={key}
                    ref={registerReference(key)}
                    className={
                      key === activeReferenceKey
                        ? "reader-ref-card is-active"
                        : "reader-ref-card"
                    }
                  >
                    <div className="reader-ref-header">
                      <div className="reader-ref-title">
                        Reference {ref.index}
                      </div>
                      {ref.doi && (
                        <span className="reader-badge-inline">DOI</span>
                      )}
                    </div>
                    <div className="reader-ref-meta">
                      {ref.doi || "DOI not available"}
                    </div>
                    <div className="reader-ref-actions">
                      {ref.doi && (
                        <button
                          type="button"
                          className="reader-action"
                          onClick={() => copyToClipboard(ref.doi)}
                        >
                          Copy DOI
                        </button>
                      )}
                      {ref.doi && (
                        <a
                          className="reader-action"
                          href={`https://doi.org/${ref.doi}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open
                        </a>
                      )}
                      <button
                        type="button"
                        className="reader-action"
                        onClick={() => toggleReferenceRaw(key)}
                      >
                        {expanded ? "Hide raw" : "Show raw"}
                      </button>
                    </div>
                    {expanded && (
                      <div className="reader-ref-raw">{ref.raw}</div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === "stats" && (
          <div className="reader-card reader-panel">
            <div className="reader-card-title">Stats</div>
            <div className="reader-stats">
              <div className="reader-stat-card">
                <div className="reader-stat-label">Pages</div>
                <div className="reader-stat-value">{effectiveStats.pages_total}</div>
              </div>
              <div className="reader-stat-card">
                <div className="reader-stat-label">Snippets</div>
                <div className="reader-stat-value">{effectiveStats.snippets_total}</div>
              </div>
              <div className="reader-stat-card">
                <div className="reader-stat-label">References</div>
                <div className="reader-stat-value">{effectiveStats.references_total}</div>
              </div>
              <div className="reader-stat-card">
                <div className="reader-stat-label">DOIs</div>
                <div className="reader-stat-value">{effectiveStats.dois_total}</div>
              </div>
            </div>
            {effectiveStats.engine_used && (
              <div className="reader-muted">Engine: {effectiveStats.engine_used}</div>
            )}
            {Number.isFinite(Number(effectiveStats.time_ms)) && (
              <div className="reader-muted">Time: {effectiveStats.time_ms} ms</div>
            )}
          </div>
        )}
      </aside>

      <section className="reader-main">
        <div className="reader-main-header">
          <div>
            <div className="reader-title">PaperCraft Reader</div>
            <div className="reader-muted">
              Source: {resolvedPdfUrl ? "PDF loaded" : "No PDF"}
            </div>
            {highlightNotice && (
              <div className="reader-notice">{highlightNotice}</div>
            )}
          </div>
        </div>

        <div className="reader-viewer-shell" ref={viewerShellRef}>
          <PdfViewer
            pdfUrl={resolvedPdfUrl}
            selectedMention={selectedSnippet}
            onHighlight={handleHighlight}
            viewerRef={viewerRef}
          />

          {selectedSnippet && (
            <div className="reader-popover">
              <div className="reader-popover-title">Snippet</div>
              <div className="reader-popover-item">
                <strong>Type:</strong> {selectedSnippet.type}
              </div>
              <div className="reader-popover-item">
                <strong>Page:</strong> {selectedSnippet.page || "?"}
              </div>
              {Number.isFinite(Number(selectedSnippet.confidence)) && (
                <div className="reader-popover-item">
                  <strong>Confidence:</strong>{" "}
                  {Number(selectedSnippet.confidence).toFixed(2)}
                </div>
              )}
              <div className="reader-popover-snippet">{selectedSnippet.snippet}</div>
            </div>
          )}

          {activeCitation && citationPopoverStyle && (
            <div
              className="reader-citation-popover"
              style={citationPopoverStyle}
            >
              <div className="reader-popover-title">
                Citation {activeCitation.label}
              </div>
              {linkedReferences.length === 0 ? (
                <div className="reader-muted">
                  Citation {activeCitation.label} (no linked).
                </div>
              ) : (
                linkedReferences.map((ref) => {
                  const preview =
                    ref.raw.length > 220 ? `${ref.raw.slice(0, 220)}…` : ref.raw;
                  return (
                    <div key={referenceKey(ref)} className="reader-citation-ref">
                      <div className="reader-ref-title">
                        Reference {ref.index}
                      </div>
                      <div className="reader-ref-preview">{preview}</div>
                      {ref.doi && (
                        <div className="reader-ref-meta">DOI: {ref.doi}</div>
                      )}
                      <div className="reader-ref-actions">
                        {ref.doi && (
                          <button
                            type="button"
                            className="reader-action"
                            onClick={() => copyToClipboard(ref.doi)}
                          >
                            Copy DOI
                          </button>
                        )}
                        {ref.doi && (
                          <a
                            className="reader-action"
                            href={`https://doi.org/${ref.doi}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open
                          </a>
                        )}
                        <button
                          type="button"
                          className="reader-action"
                          onClick={() => handleViewReference(ref)}
                        >
                          Ver en References
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
