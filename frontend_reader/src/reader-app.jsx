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
  ScrollContext,
  TransformContext,
  scrollToPdfPageIndex,
  ZoomInButton,
  ZoomOutButton,
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
const INLINE_CITATION_REGEX = /\[(\d+(?:\s*[,;]\s*\d+|\s*[-\u2013\u2014]\s*\d+)*)\]/g;
const ENGINES_ENDPOINT = "/citations/api/extractor-engines/";
const EXTRACT_ENDPOINT = "/citations/api/extract-citations/";

const MAX_CITATION_RANGE = 50;
const HIGHLIGHT_TOKEN_LIMIT = 60;
const BUILD_ID =
  typeof __READER_BUILD_ID__ !== "undefined" ? __READER_BUILD_ID__ : "";

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

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

function extractBracketNumbers(text) {
  if (!text) return [];
  const regex = new RegExp(INLINE_CITATION_REGEX.source, "g");
  const numbers = new Set();
  for (const match of text.matchAll(regex)) {
    const parsed = parseCitationNumbers(match[0]);
    parsed.forEach((num) => numbers.add(num));
  }
  return Array.from(numbers);
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

function buildSnippetsFromResults(results) {
  if (!Array.isArray(results)) return [];
  return results
    .map((item, index) => {
      const pageValue = Number(item?.page);
      const page = Number.isFinite(pageValue) && pageValue > 0 ? pageValue : null;
      const snippet =
        item?.snippet ||
        item?.fragment ||
        item?.raw?.snippet ||
        item?.raw?.match ||
        "";
      if (!snippet) return null;
      return {
        id: item?.id || `${item?.ref || "hit"}-${item?.idx || index + 1}`,
        page,
        snippet,
        type: normalizeSnippetType(item?.type || item?.pattern || item?.kind),
        confidence: Number(item?.confidence || 0),
      };
    })
    .filter(Boolean);
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
    const token = part.replace(/[\u2013\u2014]/g, "-").trim();
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
    nodes.push({ node, span, start, end });
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
    const snippetStart = Math.max(0, startOffset - 180);
    const snippetEnd = Math.min(text.length, endOffset + 180);
    const snippet = text
      .slice(snippetStart, snippetEnd)
      .replace(/\s+/g, " ")
      .trim();
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
          snippet,
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
    if (!mention || !Number.isFinite(pageNumber)) {
      return;
    }

    const token = `${pageNumber}-${mention.snippet?.slice(0, 64) || ""}-${mention.reference_index || ""}`;
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

      const { text, nodes } = buildTextLayerIndex(textLayer);
      if (!text) return;
      const highlightMode = mention.highlightMode || "snippet";
      const snippetText = String(mention.snippet || "").trim();
      const referenceIndex = Number(mention.reference_index);
      let matched = false;

      const applyParagraphHighlight = (indices) => {
        if (!indices.length) return;
        const matchedRects = indices
          .map((idx) => nodes[idx]?.span)
          .filter(Boolean)
          .map((span) => span.getBoundingClientRect());
        if (!matchedRects.length) return;
        let lineHeight = matchedRects.length
          ? matchedRects.reduce((sum, rect) => sum + rect.height, 0) /
            matchedRects.length
          : 16;
        if (!Number.isFinite(lineHeight) || lineHeight <= 0) {
          lineHeight = 16;
        }
        const lineGapThreshold = lineHeight * 1.6;
        const lineTops = Array.from(
          new Set(
            nodes
              .map((node) => {
                const rect = node.span.getBoundingClientRect();
                return Math.round(rect.top);
              })
              .filter((value) => Number.isFinite(value))
          )
        ).sort((a, b) => a - b);
        const minTop = Math.min(...matchedRects.map((rect) => rect.top));
        const maxBottom = Math.max(...matchedRects.map((rect) => rect.bottom));
        let startLine = lineTops.findIndex((top) => top >= minTop - 1);
        let endLine = lineTops.findIndex((top) => top >= maxBottom - 1);
        if (startLine === -1) startLine = 0;
        if (endLine === -1) endLine = lineTops.length - 1;
        while (
          startLine > 0 &&
          lineTops[startLine] - lineTops[startLine - 1] <= lineGapThreshold
        ) {
          startLine -= 1;
        }
        while (
          endLine < lineTops.length - 1 &&
          lineTops[endLine + 1] - lineTops[endLine] <= lineGapThreshold
        ) {
          endLine += 1;
        }
        const startTop = lineTops[startLine];
        const endTop = lineTops[endLine] + lineHeight;
        nodes.forEach((node) => {
          const rect = node.span.getBoundingClientRect();
          if (rect.top >= startTop - 1 && rect.top <= endTop + 1) {
            node.span.classList.add("reader-highlight");
          }
        });
      };

      if (highlightMode === "paragraph" && Number.isFinite(referenceIndex)) {
        const regex = new RegExp(INLINE_CITATION_REGEX.source, "g");
        let match = regex.exec(text);
        while (match) {
          const numbers = parseCitationNumbers(match[0]);
          if (numbers.includes(referenceIndex)) {
            const startOffset = match.index;
            const endOffset = startOffset + match[0].length;
            const matchedIndices = [];
            nodes.forEach((node, index) => {
              if (node.start < endOffset && node.end > startOffset) {
                matched = true;
                matchedIndices.push(index);
              }
            });
            applyParagraphHighlight(matchedIndices);
            break;
          }
          match = regex.exec(text);
        }
      }

      if (snippetText) {
        const tokenLimit = highlightMode === "paragraph" ? 16 : HIGHLIGHT_TOKEN_LIMIT;
        const tokens = snippetText.split(/\s+/).slice(0, tokenLimit);
        const pattern = tokens.map(escapeRegExp).join("\\s+");
        try {
          const regex = new RegExp(pattern, "i");
          const match = regex.exec(text);
          if (!matched && match) {
            const startOffset = match.index;
            const endOffset = match.index + match[0].length;
            const matchedIndices = [];
            nodes.forEach((node, index) => {
              if (node.start < endOffset && node.end > startOffset) {
                matched = true;
                matchedIndices.push(index);
              }
            });
            if (highlightMode === "paragraph") {
              applyParagraphHighlight(matchedIndices);
            } else {
              matchedIndices.forEach((idx) => nodes[idx].span.classList.add("reader-highlight"));
            }
          }
        } catch (err) {
          matched = false;
        }
      }

      if (!matched && snippetText) {
        const normalized = snippetText.toLowerCase().replace(/\s+/g, " ").trim();
        const keywords = normalized
          .split(" ")
          .filter((word) => word.length > 3)
          .slice(0, 8);
        const matchedIndices = [];
        nodes.forEach((node, index) => {
          const spanText = (node.span.textContent || "").toLowerCase();
          if (keywords.some((word) => spanText.includes(word))) {
            matched = true;
            matchedIndices.push(index);
          }
        });
        if (matchedIndices.length) {
          if (highlightMode === "paragraph") {
            applyParagraphHighlight(matchedIndices);
          } else {
            matchedIndices.forEach((idx) => nodes[idx].span.classList.add("reader-highlight"));
          }
        }
      }

      if (typeof onHighlight === "function") {
        onHighlight(matched);
      }
    };

    const timer = setTimeout(run, 350);
    return () => clearTimeout(timer);
  }, [mention, onHighlight]);
}

function ScrollRootBinder({ viewerRef }) {
  const { setScrollRoot } = React.useContext(ScrollContext);

  useEffect(() => {
    if (!viewerRef?.current) return;
    setScrollRoot(viewerRef.current);
    return () => setScrollRoot(null);
  }, [setScrollRoot, viewerRef]);

  return null;
}

function ZoomControls() {
  const { scale, setScale } = React.useContext(TransformContext);
  const percent = Math.round(scale * 100);

  return (
    <div className="reader-toolbar-group">
      <ZoomOutButton className="reader-tool-btn" />
      <button
        type="button"
        className="reader-tool-btn reader-zoom-display"
        onClick={() => setScale(1)}
      >
        {percent}%
      </button>
      <ZoomInButton className="reader-tool-btn" />
    </div>
  );
}

function PageNavigator({ viewerRef }) {
  const { numPages } = React.useContext(DocumentContext);
  const inputRef = useRef(null);
  const currentPageRef = useRef(1);
  const [inputValue, setInputValue] = useState("1");

  useEffect(() => {
    if (numPages && currentPageRef.current > numPages) {
      currentPageRef.current = numPages;
      setInputValue(String(numPages));
    }
  }, [numPages]);

  useEffect(() => {
    const viewerEl = viewerRef?.current;
    if (!viewerEl) return;
    let rafId = null;

    const update = () => {
      rafId = null;
      const viewerRect = viewerEl.getBoundingClientRect();
      const pages = viewerEl.querySelectorAll(".pdf-reader__page");
      let bestPage = currentPageRef.current;
      let bestRatio = 0;

      pages.forEach((pageEl) => {
        const rect = pageEl.getBoundingClientRect();
        const visible = Math.min(rect.bottom, viewerRect.bottom) - Math.max(rect.top, viewerRect.top);
        if (visible <= 0) return;
        const ratio = visible / rect.height;
        if (ratio > bestRatio) {
          const pageNumber = Number(pageEl.dataset.pageNumber || pageEl.getAttribute("data-page-number"));
          if (Number.isFinite(pageNumber)) {
            bestRatio = ratio;
            bestPage = pageNumber;
          }
        }
      });

      const isEditing = document.activeElement === inputRef.current;
      if (!isEditing && bestPage && bestPage !== currentPageRef.current) {
        currentPageRef.current = bestPage;
        setInputValue(String(bestPage));
      }
    };

    const onScroll = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(update);
    };

    onScroll();
    viewerEl.addEventListener("scroll", onScroll);
    window.addEventListener("resize", onScroll);
    return () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      viewerEl.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [viewerRef]);

  const commitPage = () => {
    if (!numPages) return;
    const pageNumber = parseInt(inputValue, 10);
    if (Number.isFinite(pageNumber) && pageNumber >= 1 && pageNumber <= numPages) {
      currentPageRef.current = pageNumber;
      scrollToPdfPageIndex(pageNumber - 1);
    } else {
      setInputValue(String(currentPageRef.current));
    }
  };

  return (
    <div className="reader-toolbar-group">
      <div className="reader-page-control">
        <input
          ref={inputRef}
          type="number"
          min={1}
          max={numPages || 1}
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          onBlur={commitPage}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              commitPage();
            }
          }}
        />
        <span>/ {numPages || 0}</span>
      </div>
    </div>
  );
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
    <div className="reader-viewer">
      <ContextProvider>
        <ScrollRootBinder viewerRef={viewerRef} />
        <div className="reader-toolbar">
          <ZoomControls />
          <PageNavigator viewerRef={viewerRef} />
        </div>
        <div className="reader-scroll" ref={viewerRef}>
          <DocumentWrapper file={pdfUrl} renderType={RENDER_TYPE.MULTI_CANVAS}>
            <PdfPages />
          </DocumentWrapper>
        </div>
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
  const [activeCitation, setActiveCitation] = useState(null);
  const [citationPopoverStyle, setCitationPopoverStyle] = useState(null);
  const [activeReferenceId, setActiveReferenceId] = useState(null);
  const [highlightReferenceId, setHighlightReferenceId] = useState(null);
  const [inlineCitations, setInlineCitations] = useState([]);
  const [popoverExpanded, setPopoverExpanded] = useState(false);
  const [engineOptions, setEngineOptions] = useState([]);
  const [engineValue, setEngineValue] = useState("");
  const [extractStatus, setExtractStatus] = useState({
    loading: false,
    error: "",
    message: "",
  });
  const [activeFile, setActiveFile] = useState(previewFile || null);
  const [dropActive, setDropActive] = useState(false);

  const viewerRef = useRef(null);
  const viewerShellRef = useRef(null);
  const referenceElements = useRef(new Map());
  const citationHitMapRef = useRef(new Map());
  const activeCitationRef = useRef(null);
  const inlineCitationsKeyRef = useRef("");
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!previewFile) {
      return;
    }
    const objectUrl = URL.createObjectURL(previewFile);
    setPreviewUrl(objectUrl);
    setActiveFile(previewFile);
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
      setActiveFile(file);
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
    setPopoverExpanded(false);
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

  useEffect(() => {
    let active = true;

    fetch(ENGINES_ENDPOINT, { method: "GET" })
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((payload) => {
        if (!active) return;
        const engines = Array.isArray(payload?.engines) ? payload.engines : [];
        setEngineOptions(engines);
      })
      .catch(() => {
        if (!active) return;
        setEngineOptions([]);
      });

    return () => {
      active = false;
    };
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
      const bracketIndices = extractBracketNumbers(snippet.snippet);
      const bracketIndex =
        bracketIndices.length > 0 ? bracketIndices[0] : extractBracketIndex(snippet.snippet);
      return {
        ...snippet,
        doi_in_snippet: doi,
        bracket_indices: bracketIndices,
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

  const extractReferenceSummary = (raw) => {
    const cleaned = String(raw || "").replace(/\s+/g, " ").trim();
    if (!cleaned) {
      return { author: "", title: "" };
    }
    const stripped = cleaned.replace(/^\s*(\[(\d+)\]|(\d+)[\.\)])\s*/g, "");
    const formatAuthor = (value) => {
      const normalized = String(value || "").replace(/\s+/g, " ").trim();
      if (!normalized) return "";
      const firstChunk = normalized.split(";")[0].split(" and ")[0].trim();
      if (firstChunk.includes(",")) {
        const [lastName, rest] = firstChunk.split(",", 2);
        const initials = rest
          ? rest
              .trim()
              .split(/\s+/)
              .filter(Boolean)
              .map((token) => `${token[0].toUpperCase()}.`)
              .join(" ")
          : "";
        return initials ? `${lastName.trim()}, ${initials}` : lastName.trim();
      }
      const parts = firstChunk.split(/\s+/).filter(Boolean);
      if (parts.length >= 2) {
        const lastName = parts[parts.length - 1];
        const initial = `${parts[0][0].toUpperCase()}.`;
        return `${lastName}, ${initial}`;
      }
      return firstChunk;
    };
    const firstPeriod = stripped.indexOf(". ");
    const authorPart =
      firstPeriod !== -1 ? stripped.slice(0, firstPeriod).trim() : "";
    let remainder =
      firstPeriod !== -1 ? stripped.slice(firstPeriod + 2).trim() : "";
    if (!authorPart) {
      remainder = stripped;
    }
    remainder = remainder.replace(/^[-:,;)\]]+\s*/, "").trim();
    let title = "";
    if (remainder) {
      title = remainder.split(". ")[0].trim();
    }
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
  };

  const referenceSnippetByIndex = useMemo(() => {
    const map = new Map();
    derivedSnippets.forEach((snippet) => {
      const refIndexes = new Set();
      if (snippet.doi_in_snippet && referenceByDoi.has(snippet.doi_in_snippet)) {
        refIndexes.add(referenceByDoi.get(snippet.doi_in_snippet).index);
      }
      if (Array.isArray(snippet.bracket_indices)) {
        snippet.bracket_indices.forEach((value) => {
          if (Number.isFinite(value) && referenceByIndex.has(value)) {
            refIndexes.add(value);
          }
        });
      }
      refIndexes.forEach((refIndex) => {
        const current = map.get(refIndex);
        if (!current || snippet.snippet.length > current.snippet.length) {
          map.set(refIndex, snippet);
        }
      });
    });
    return map;
  }, [derivedSnippets, referenceByDoi, referenceByIndex]);

  const resolvedPdfUrl = previewUrl || data?.pdf_url || pdfUrl || "";
  const canExtract = Boolean(engineValue) && !extractStatus.loading;

  const citationStatsByReference = useMemo(() => {
    const map = new Map();
    inlineCitations.forEach((hit) => {
      if (!Array.isArray(hit.numbers)) return;
      hit.numbers.forEach((number) => {
        if (!Number.isFinite(number)) return;
        const entry = map.get(number) || { count: 0, pages: new Set() };
        entry.count += 1;
        if (Number.isFinite(hit.page)) {
          entry.pages.add(hit.page);
        }
        map.set(number, entry);
      });
    });
    return map;
  }, [inlineCitations]);

  const inlineSnippetByIndex = useMemo(() => {
    const map = new Map();
    inlineCitations.forEach((hit) => {
      if (!Array.isArray(hit.numbers) || !hit.snippet) return;
      hit.numbers.forEach((number) => {
        if (!Number.isFinite(number)) return;
        const current = map.get(number);
        if (!current || hit.snippet.length > current.snippet.length) {
          map.set(number, { snippet: hit.snippet, page: hit.page || null });
        }
      });
    });
    return map;
  }, [inlineCitations]);

  const referencesWithStats = useMemo(() => {
    return filteredReferences.map((ref) => {
      const statsEntry = citationStatsByReference.get(ref.index);
      const pages = statsEntry
        ? Array.from(statsEntry.pages).sort((a, b) => a - b)
        : [];
      const linkedSnippet =
        referenceSnippetByIndex.get(ref.index) || inlineSnippetByIndex.get(ref.index) || null;
      const summary = extractReferenceSummary(ref.raw);
      const snippetPage = linkedSnippet ? Number(linkedSnippet.page) : null;
      let displayPage = null;
      if (pages.length) {
        displayPage = pages[0];
      } else if (Number.isFinite(snippetPage)) {
        displayPage = snippetPage;
      }
      return {
        ...ref,
        cited_count: statsEntry ? statsEntry.count : 0,
        cited_pages: pages,
        display_page: displayPage,
        display_snippet: linkedSnippet ? linkedSnippet.snippet : "",
        display_author: summary.author,
        display_title: summary.title,
      };
    });
  }, [
    filteredReferences,
    citationStatsByReference,
    referenceSnippetByIndex,
    inlineSnippetByIndex,
  ]);

  const activeCitationRefIndex = useMemo(() => {
    if (!activeCitation || !Array.isArray(activeCitation.numbers)) return null;
    const value = activeCitation.numbers.find((num) => Number.isFinite(num));
    return Number.isFinite(value) ? value : null;
  }, [activeCitation]);

  const activeCitationReference = useMemo(() => {
    if (!activeCitationRefIndex) return null;
    return referenceByIndex.get(activeCitationRefIndex) || null;
  }, [activeCitationRefIndex, referenceByIndex]);

  const citationsForActiveReference = useMemo(() => {
    if (!activeCitationRefIndex) return [];
    return inlineCitations.filter((hit) =>
      Array.isArray(hit.numbers) && hit.numbers.includes(activeCitationRefIndex)
    );
  }, [inlineCitations, activeCitationRefIndex]);
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
        const hitsList = [];
        pages.forEach((pageEl) => {
          if (!pageEl) return;
          const hits = collectCitationHitsForPage(pageEl);
          hits.forEach((hit) => hitsList.push(hit));
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
              hitEl.dataset.citationRefs = hit.numbers.join(",");
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
        const nextKey = hitsList.map((hit) => hit.id).join("|");
        if (inlineCitationsKeyRef.current !== nextKey) {
          inlineCitationsKeyRef.current = nextKey;
          setInlineCitations(hitsList);
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

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl) return;
    viewerEl
      .querySelectorAll(".citation-hit.is-linked")
      .forEach((el) => el.classList.remove("is-linked"));
    if (!highlightReferenceId) return;
    viewerEl.querySelectorAll(".citation-hit").forEach((el) => {
      const refs = (el.dataset.citationRefs || "")
        .split(",")
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));
      if (refs.includes(highlightReferenceId)) {
        el.classList.add("is-linked");
      }
    });
  }, [highlightReferenceId]);

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

  const ensurePdfFile = async () => {
    if (activeFile) return activeFile;
    if (!resolvedPdfUrl) return null;
    try {
      const res = await fetch(resolvedPdfUrl);
      if (!res.ok) return null;
      const blob = await res.blob();
      if (!blob || !blob.size) return null;
      return new File([blob], "document.pdf", {
        type: blob.type || "application/pdf",
      });
    } catch (err) {
      return null;
    }
  };

  const buildExtractionResult = (payload) => {
    const snippets =
      Array.isArray(payload?.snippets) && payload.snippets.length
        ? payload.snippets
        : buildSnippetsFromResults(payload?.results);
    const references = Array.isArray(payload?.references)
      ? payload.references
      : [];
    const baseStats =
      payload?.stats && typeof payload.stats === "object" ? payload.stats : {};
    const stats = {
      pages_total: Number(baseStats.pages_total || 0),
      snippets_total:
        typeof baseStats.snippets_total === "number"
          ? baseStats.snippets_total
          : snippets.length,
      references_total: Number(baseStats.references_total || references.length),
      dois_total: Number(baseStats.dois_total || 0),
      engine_used: baseStats.engine_used || payload?.engine_used || "",
      time_ms: Number.isFinite(Number(baseStats.time_ms))
        ? Number(baseStats.time_ms)
        : (Number.isFinite(Number(payload?.time_ms)) ? Number(payload.time_ms) : null),
      references_numbered: Boolean(baseStats.references_numbered),
    };
    return { snippets, references, stats };
  };

  const handleExtract = async () => {
    if (!engineValue) {
      setExtractStatus({
        loading: false,
        error: "Selecciona un motor antes de extraer.",
        message: "",
      });
      return;
    }

    setExtractStatus({ loading: true, error: "", message: "" });
    const file = await ensurePdfFile();
    if (!file) {
      setExtractStatus({
        loading: false,
        error: "No hay PDF disponible para extraer.",
        message: "",
      });
      return;
    }

    try {
      const fd = new FormData();
      fd.append("manuscript", file);
      fd.append("engine", engineValue);

      const res = await fetch(EXTRACT_ENDPOINT, { method: "POST", body: fd });
      const payload = await res.json();
      if (!payload?.ok) {
        setExtractStatus({
          loading: false,
          error: payload?.error || "No se pudo extraer citas.",
          message: "",
        });
        return;
      }

      const result = buildExtractionResult(payload);
      setSnippetsData(result.snippets);
      setReferencesData(result.references);
      setStats(result.stats);
      setActiveTab("snippets");
      setExtractStatus({
        loading: false,
        error: "",
        message: "Extraccion completada.",
      });
    } catch (err) {
      setExtractStatus({
        loading: false,
        error: "Error de red al extraer.",
        message: "",
      });
    }
  };

  const handleViewReference = (ref) => {
    const key = referenceKey(ref);
    if (key) {
      jumpToReference(key);
    }
    setActiveReferenceId(ref.index);
    setHighlightReferenceId(ref.index);
    const linkedSnippet =
      referenceSnippetByIndex.get(ref.index) || inlineSnippetByIndex.get(ref.index);
    if (linkedSnippet) {
      const snippetPayload = linkedSnippet.snippet
        ? linkedSnippet
        : { snippet: String(linkedSnippet || "") };
      setSelectedSnippet({
        ...snippetPayload,
        id: linkedSnippet.id || `inline-${ref.index}`,
        page: linkedSnippet.page || ref.display_page || null,
        type: linkedSnippet.type || "bracket",
        confidence: linkedSnippet.confidence || 0,
        reference_index: ref.index,
        highlightMode: "paragraph",
      });
    }
  };

  const handleReferenceSelect = (ref) => {
    setActiveReferenceKey(referenceKey(ref));
    setActiveReferenceId(ref.index);
    setHighlightReferenceId(ref.index);
    const linkedSnippet =
      referenceSnippetByIndex.get(ref.index) || inlineSnippetByIndex.get(ref.index);
    if (linkedSnippet) {
      const snippetPayload = linkedSnippet.snippet
        ? linkedSnippet
        : { snippet: String(linkedSnippet || "") };
      setSelectedSnippet({
        ...snippetPayload,
        id: linkedSnippet.id || `inline-${ref.index}`,
        page: linkedSnippet.page || ref.display_page || null,
        type: linkedSnippet.type || "bracket",
        confidence: linkedSnippet.confidence || 0,
        reference_index: ref.index,
        highlightMode: "paragraph",
      });
      if (Number.isFinite(Number(linkedSnippet.page))) {
        scrollToPdfPageIndex(Number(linkedSnippet.page) - 1);
        return;
      }
    }
    const statsEntry = citationStatsByReference.get(ref.index);
    if (statsEntry && statsEntry.pages.size) {
      const pages = Array.from(statsEntry.pages).sort((a, b) => a - b);
      if (pages[0]) {
        scrollToPdfPageIndex(pages[0] - 1);
      }
    }
  };

  const handleToggleHighlightAll = () => {
    if (!activeCitationRefIndex) return;
    setHighlightReferenceId((current) =>
      current === activeCitationRefIndex ? null : activeCitationRefIndex
    );
  };

  const handleNextCitation = (offset) => {
    if (!citationsForActiveReference.length) return;
    const currentIndex = citationsForActiveReference.findIndex(
      (hit) => hit.id === activeCitation?.id
    );
    const baseIndex = currentIndex === -1 ? 0 : currentIndex;
    const nextIndex =
      (baseIndex + offset + citationsForActiveReference.length) %
      citationsForActiveReference.length;
    const next = citationsForActiveReference[nextIndex];
    if (next) {
      setActiveCitation(next);
      if (Number.isFinite(next.page)) {
        scrollToPdfPageIndex(next.page - 1);
      }
    }
  };

  const applyPdfFile = (file) => {
    if (!file) return;
    if (file.type !== "application/pdf") {
      setExtractStatus({
        loading: false,
        error: "Selecciona un PDF valido.",
        message: "",
      });
      return;
    }
    setActiveFile(file);
    setPreviewUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return URL.createObjectURL(file);
    });
    setSnippetsData([]);
    setReferencesData([]);
    setStats(null);
    setSelectedSnippet(null);
    setActiveCitation(null);
    setExtractStatus({ loading: false, error: "", message: "PDF actualizado." });
  };

  const handlePdfChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    applyPdfFile(file);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDropActive(false);
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    applyPdfFile(file);
  };

  const handleClearPdf = () => {
    setActiveFile(null);
    setPreviewUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return "";
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    setExtractStatus({ loading: false, error: "", message: "PDF eliminado." });
  };

  const dropzoneLabel = useMemo(() => {
    if (!activeFile) {
      return "Arrastra un PDF aqui o haz clic para seleccionarlo";
    }
    const sizeKb = Math.round(activeFile.size / 1024);
    return `${activeFile.name} - ${sizeKb} KB`;
  }, [activeFile]);

  const extractionToolbar = (
    <div className="reader-extract-controls">
      <div
        className={dropActive ? "reader-dropzone is-active" : "reader-dropzone"}
        onClick={() => fileInputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          setDropActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDropActive(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setDropActive(false);
        }}
        onDrop={handleDrop}
      >
        <span className="reader-dropzone-text">{dropzoneLabel}</span>
        {activeFile && (
          <button
            type="button"
            className="reader-dropzone-clear"
            onClick={(event) => {
              event.stopPropagation();
              handleClearPdf();
            }}
          >
            x
          </button>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        className="reader-file-input"
        onChange={handlePdfChange}
      />
      <select
        className="reader-engine-select"
        value={engineValue}
        onChange={(event) => setEngineValue(event.target.value)}
      >
        <option value="" disabled>
          Selecciona herramienta...
        </option>
        {engineOptions.map((engine) => (
          <option
            key={engine.key}
            value={engine.key}
            disabled={engine.available === false}
          >
            {engine.label || engine.key}
            {engine.available === false ? " (Proximamente)" : ""}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="reader-tool-btn"
        onClick={handleExtract}
        disabled={!canExtract}
      >
        {extractStatus.loading ? "Extrayendo..." : "Extraer"}
      </button>
      {(extractStatus.error || extractStatus.message) && (
        <div
          className={
            extractStatus.error
              ? "reader-extract-status is-error"
              : "reader-extract-status"
          }
        >
          {extractStatus.error || extractStatus.message}
        </div>
      )}
    </div>
  );

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
          <button
            type="button"
            className={
              activeTab === "extract"
                ? "reader-tab is-active"
                : "reader-tab"
            }
            onClick={() => setActiveTab("extract")}
          >
            Extraer
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
            ) : referencesWithStats.length === 0 ? (
              <div className="reader-muted">No references match your filters.</div>
            ) : (
              referencesWithStats.map((ref) => {
                const key = referenceKey(ref);
                const isActive = key === activeReferenceKey;
                const pageLabel = Number.isFinite(ref.display_page)
                  ? `p. ${ref.display_page}`
                  : "p. -";
                const snippetText = ref.display_snippet || "";
                const footerAuthor = ref.display_author || (ref.index ? `Ref #${ref.index}` : "Reference");
                const footerTitle = ref.display_title || "";
                return (
                  <button
                    type="button"
                    key={key}
                    ref={registerReference(key)}
                    className={
                      isActive
                        ? "reader-ref-row is-active"
                        : "reader-ref-row"
                    }
                    onClick={() => handleReferenceSelect(ref)}
                  >
                    <div className="reader-ref-top">
                      <span className="reader-ref-index">
                        {ref.index ? `#${ref.index}` : "-"}
                      </span>
                      <span className="reader-ref-page">{pageLabel}</span>
                    </div>
                    <div
                      className={
                        snippetText ? "reader-ref-snippet" : "reader-ref-snippet is-muted"
                      }
                    >
                      <span className="reader-ref-snippet-text">
                        {snippetText ? `"${snippetText}"` : "\"No snippet linked yet.\""}
                      </span>
                    </div>
                    <div className="reader-ref-footer">
                      <div className="reader-ref-footer-main">
                        <span className="reader-ref-title">{footerTitle || "Sin titulo"}</span>
                        {footerAuthor && (
                          <span className="reader-ref-author"> - {footerAuthor}</span>
                        )}
                      </div>
                      {ref.doi && <div className="reader-ref-doi">DOI: {ref.doi}</div>}
                    </div>
                  </button>
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
            {BUILD_ID && <div className="reader-muted">Build: {BUILD_ID}</div>}
          </div>
        )}

        {activeTab === "extract" && (
          <div className="reader-card reader-panel">
            <div className="reader-card-title">Extraccion</div>
            {extractionToolbar}
          </div>
        )}
      </aside>

      <section className="reader-main">
        {highlightNotice && (
          <div className="reader-main-header">
            <div className="reader-notice">{highlightNotice}</div>
          </div>
        )}

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
              {activeCitationRefIndex && (
                <div className="reader-ref-badge">
                  Reference #{activeCitationRefIndex}
                </div>
              )}
              {!activeCitationReference ? (
                <div className="reader-muted">
                  Citation {activeCitation.label} (no linked).
                </div>
              ) : (
                <div className="reader-citation-ref">
                  {activeCitationReference.doi && (
                    <div className="reader-ref-meta">
                      DOI: {activeCitationReference.doi}
                    </div>
                  )}
                  <div className="reader-ref-preview">
                    {popoverExpanded
                      ? activeCitationReference.raw
                      : `${activeCitationReference.raw.slice(0, 240)}${
                          activeCitationReference.raw.length > 240 ? "..." : ""
                        }`}
                  </div>
                  <button
                    type="button"
                    className="reader-link-btn"
                    onClick={() => setPopoverExpanded((prev) => !prev)}
                  >
                    {popoverExpanded ? "Collapse" : "Expand"}
                  </button>
                  <div className="reader-ref-actions">
                    {activeCitationReference.doi && (
                      <button
                        type="button"
                        className="reader-action"
                        onClick={() => copyToClipboard(activeCitationReference.doi)}
                      >
                        Copy DOI
                      </button>
                    )}
                    {activeCitationReference.doi && (
                      <a
                        className="reader-action"
                        href={`https://doi.org/${activeCitationReference.doi}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    )}
                    <button
                      type="button"
                      className="reader-action"
                      onClick={handleToggleHighlightAll}
                    >
                      {highlightReferenceId === activeCitationRefIndex
                        ? "Clear highlights"
                        : "Highlight all citations"}
                    </button>
                    <button
                      type="button"
                      className="reader-action"
                      onClick={() => handleNextCitation(-1)}
                      disabled={citationsForActiveReference.length <= 1}
                    >
                      Prev citation
                    </button>
                    <button
                      type="button"
                      className="reader-action"
                      onClick={() => handleNextCitation(1)}
                      disabled={citationsForActiveReference.length <= 1}
                    >
                      Next citation
                    </button>
                    <button
                      type="button"
                      className="reader-action"
                      onClick={() => handleViewReference(activeCitationReference)}
                    >
                      Jump to References tab
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
