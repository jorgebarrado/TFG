import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
const BRACKET_REGEX = /\[\s*(\d+)\s*\]/;
const INLINE_CITATION_REGEX = /\[\s*(\d+(?:\s*[,;]\s*\d+|\s*[-\u2013\u2014]\s*\d+)*)\s*\]/g;

// Patrones autor-anio y DOI (espejo de citation_patterns.py). Necesitan
// soportar marcas combinantes (\u0300-\u036f) porque el texto del PDF se
// normaliza a NFKD antes de matchear.
const _NAME_TOKEN =
  "[A-Z\\u00C0-\\u00DC\\u0100-\\u017F]" +
  "[A-Za-z\\u00C0-\\u00FF\\u0100-\\u017F\\u0300-\\u036F'\\-]+";
const _AUTHOR_GROUP =
  `${_NAME_TOKEN}` +
  `(?:` +
  `\\s+et\\s+al\\.?` +
  `|\\s+(?:and|&)\\s+${_NAME_TOKEN}` +
  `|(?:,\\s+${_NAME_TOKEN}){1,3}(?:,?\\s+(?:and|&)\\s+${_NAME_TOKEN})?` +
  `)?`;
const _YEAR = "(?:1[5-9]|20)\\d{2}[a-z]?";
const _YEAR_LIST = `${_YEAR}(?:\\s*,\\s*${_YEAR})*`;
const NARRATIVE_AUTHOR_YEAR_REGEX = new RegExp(
  `\\b${_AUTHOR_GROUP}\\s*\\(\\s*${_YEAR_LIST}\\s*\\)`,
  "g"
);
const _PAREN_ITEM = `${_AUTHOR_GROUP}(?:\\s*,)?\\s+${_YEAR}`;
const PARENTHETICAL_AUTHOR_YEAR_REGEX = new RegExp(
  `\\(\\s*${_PAREN_ITEM}(?:\\s*[;]\\s*${_PAREN_ITEM})*\\s*\\)`,
  "g"
);
const INLINE_DOI_REGEX = /10\.\d{4,9}\/[^\s"<>]+/gi;
const AUTHOR_YEAR_FALSE_HEADS = new Set([
  "figure", "fig", "figures", "figs",
  "table", "tables", "tab",
  "section", "sections", "sec",
  "chapter", "chapters", "ch",
  "page", "pages", "pg",
  "equation", "equations", "eq", "eqs",
  "theorem", "theorems",
  "lemma", "lemmas",
  "corollary", "corollaries",
  "definition", "definitions",
  "proposition", "propositions",
  "algorithm", "algorithms", "alg",
  "listing", "listings",
  "appendix", "appendices", "app",
  "volume", "volumes", "vol",
  "issue", "no", "number", "numbers",
  "part", "parts",
  "step", "steps",
  "phase", "phases",
  "case", "cases",
  "example", "examples", "ex",
]);

function looksLikeFalseAuthorHead(text) {
  const head = String(text || "").trim().split(/\s+/)[0] || "";
  return AUTHOR_YEAR_FALSE_HEADS.has(head.toLowerCase());
}

function getCookieValue(name) {
  const target = `${name}=`;
  return String(document.cookie || "")
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(target))
    ?.slice(target.length) || "";
}

function elementFromSelectionNode(node) {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
}

function getReaderSelectionPayload(viewerEl) {
  const selection = window.getSelection?.();
  const text = String(selection?.toString() || "").trim();
  if (!selection || !text || !selection.rangeCount) {
    return null;
  }

  const anchorEl = elementFromSelectionNode(selection.anchorNode);
  const focusEl = elementFromSelectionNode(selection.focusNode);
  const pageEl =
    anchorEl?.closest?.(".pdf-reader__page") ||
    focusEl?.closest?.(".pdf-reader__page") ||
    null;
  if (viewerEl && pageEl && !viewerEl.contains(pageEl)) {
    return null;
  }

  const pageNumber = Number(
    pageEl?.dataset?.pageNumber || pageEl?.getAttribute?.("data-page-number")
  );
  const page = Number.isFinite(pageNumber) && pageNumber > 0 ? pageNumber : null;
  const range = selection.getRangeAt(0);
  const pageRect = pageEl?.getBoundingClientRect?.();
  const boxes =
    pageRect
      ? Array.from(range.getClientRects())
          .filter((rect) => rect.width > 0 && rect.height > 0)
          .slice(0, 24)
          .map((rect) => ({
            left: Math.max(0, rect.left - pageRect.left),
            top: Math.max(0, rect.top - pageRect.top),
            width: rect.width,
            height: rect.height,
          }))
      : [];

  return { text, page, boxes };
}

function stripDoiTrailing(value) {
  let cleaned = String(value || "");
  while (cleaned.length) {
    const last = cleaned[cleaned.length - 1];
    if (".,;:!?)]}>".indexOf(last) === -1) break;
    if (last === ")" && (cleaned.match(/\(/g) || []).length > (cleaned.match(/\)/g) || []).length) {
      break;
    }
    cleaned = cleaned.slice(0, -1);
  }
  return cleaned;
}
const EXTRACT_ENDPOINT = "/citations/api/extract-citations/";
const DETECT_ARTICLE_DOI_ENDPOINT = "/citations/api/detect-article-doi/";
const PREVIEW_EXTRACT_ENGINE = "papermage";

const MAX_CITATION_RANGE = 50;
const HIGHLIGHT_TOKEN_LIMIT = 60;
const BUILD_ID =
  typeof __READER_BUILD_ID__ !== "undefined" ? __READER_BUILD_ID__ : "";
const READER_V2_LAYER_LABELS = Object.freeze({
  tokens: "Tokens",
  rows: "Rows",
  paragraphs: "Paragraphs",
  bibliographies: "Bibliographies",
  sections: "Sections",
});

function getApproxExtractProgressStep(value) {
  if (value < 18) return 5;
  if (value < 36) return 4;
  if (value < 54) return 3;
  if (value < 74) return 2;
  if (value < 88) return 1;
  return 0.4;
}

function getApproxExtractProgressLabel(value) {
  if (value < 12) return "Preparando PDF...";
  if (value < 28) return "Subiendo PDF y preparando extraccion...";
  if (value < 46) return "Leyendo paginas del documento...";
  if (value < 66) return "Detectando referencias y citas...";
  if (value < 84) return "Relacionando resultados...";
  return "Finalizando la extraccion...";
}

function getReaderV2LayerKeys(data) {
  const rawLayers = data?.layers;
  if (!rawLayers || typeof rawLayers !== "object") {
    if (Array.isArray(data?.items)) {
      return ["tokens"];
    }
    return [];
  }
  return Object.keys(rawLayers).filter((layerKey) => Array.isArray(rawLayers[layerKey]));
}

function pickDefaultReaderV2Layer(data) {
  const layerKeys = getReaderV2LayerKeys(data);
  if (!layerKeys.length) return "";
  if (layerKeys.includes("tokens")) return "tokens";
  return layerKeys[0];
}

function getReaderV2ItemId(item, index, layerKey = "layer") {
  const rawId = item?.id;
  if (rawId !== undefined && rawId !== null && String(rawId).trim()) {
    return String(rawId);
  }
  const pageValue = Number(item?.page);
  const safePage = Number.isFinite(pageValue) ? pageValue : "x";
  return `${layerKey}-${safePage}-${index}`;
}

function getReaderV2SourceId(item, index, layerKey = "layer") {
  if (String(layerKey || "").toLowerCase() === "tokens") {
    const tokenId = item?.token_id;
    if (tokenId !== undefined && tokenId !== null && String(tokenId).trim()) {
      return String(tokenId);
    }
  }
  return getReaderV2ItemId(item, index, layerKey);
}

function normalizeOverlayPage(value) {
  const page = Number(value);
  if (!Number.isFinite(page) || page < 0) return null;
  return page;
}

function normalizeOverlayBox(box) {
  if (!Array.isArray(box) || box.length < 4) return null;
  const x = Number(box[0]);
  const y = Number(box[1]);
  const width = Number(box[2]);
  const height = Number(box[3]);
  if (![x, y, width, height].every((value) => Number.isFinite(value))) return null;
  if (width <= 0 || height <= 0) return null;
  const clampedX = Math.max(0, Math.min(1, x));
  const clampedY = Math.max(0, Math.min(1, y));
  const clampedWidth = Math.max(0, Math.min(1 - clampedX, width));
  const clampedHeight = Math.max(0, Math.min(1 - clampedY, height));
  if (clampedWidth <= 0 || clampedHeight <= 0) return null;
  return [clampedX, clampedY, clampedWidth, clampedHeight];
}

const READER_V2_SHRINK_BY_LAYER = Object.freeze({
  tokens: { padX: 0.0012, padY: 0.0010 },
  rows: { padX: 0.0005, padY: 0.00035 },
  paragraphs: { padX: 0.0016, padY: 0.0013 },
  bibliographies: { padX: 0.0014, padY: 0.0011 },
  sections: { padX: 0.0002, padY: 0.00015 },
  default: { padX: 0.0008, padY: 0.0006 },
});

const READER_V2_SORT_TOLERANCE_BY_LAYER = Object.freeze({
  tokens: 0.0022,
  rows: 0.0048,
  paragraphs: 0.0062,
  bibliographies: 0.0062,
  sections: 0.0054,
  default: 0.0045,
});

function getReaderV2SortTolerance(layerName) {
  const key = String(layerName || "").toLowerCase();
  return READER_V2_SORT_TOLERANCE_BY_LAYER[key] || READER_V2_SORT_TOLERANCE_BY_LAYER.default;
}

function getAdjustedBox(rawBox, layerName) {
  const source = Array.isArray(rawBox)
    ? {
        x: Number(rawBox[0]),
        y: Number(rawBox[1]),
        width: Number(rawBox[2]),
        height: Number(rawBox[3]),
      }
    : {
        x: Number(rawBox?.x),
        y: Number(rawBox?.y),
        width: Number(rawBox?.width),
        height: Number(rawBox?.height),
      };

  if (![source.x, source.y, source.width, source.height].every((value) => Number.isFinite(value))) {
    return null;
  }
  if (source.width <= 0 || source.height <= 0) {
    return null;
  }

  const key = String(layerName || "").toLowerCase();
  const shrink = READER_V2_SHRINK_BY_LAYER[key] || READER_V2_SHRINK_BY_LAYER.default;
  const safePadX = Math.min(Math.max(0, shrink.padX), source.width * 0.24);
  const safePadY = Math.min(Math.max(0, shrink.padY), source.height * 0.24);
  const minWidth = Math.min(source.width, Math.max(0.00018, source.width * 0.22));
  const minHeight = Math.min(source.height, Math.max(0.00018, source.height * 0.22));

  const nextWidth = Math.min(
    source.width,
    Math.max(source.width - 2 * safePadX, minWidth)
  );
  const nextHeight = Math.min(
    source.height,
    Math.max(source.height - 2 * safePadY, minHeight)
  );

  let nextX = source.x + (source.width - nextWidth) / 2;
  let nextY = source.y + (source.height - nextHeight) / 2;
  nextX = Math.max(0, Math.min(1 - nextWidth, nextX));
  nextY = Math.max(0, Math.min(1 - nextHeight, nextY));

  return {
    x: nextX,
    y: nextY,
    width: nextWidth,
    height: nextHeight,
  };
}

function sortItemsByReadingOrder(items, layerName) {
  if (!Array.isArray(items) || items.length <= 1) {
    return Array.isArray(items) ? [...items] : [];
  }

  const tolerance = Math.max(0.0002, getReaderV2SortTolerance(layerName));
  const toNum = (value, fallback = 0) => {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
  };

  return [...items].sort((itemA, itemB) => {
    const pageA = Math.max(0, toNum(itemA?.page, 0));
    const pageB = Math.max(0, toNum(itemB?.page, 0));
    if (pageA !== pageB) return pageA - pageB;

    const boxA = Array.isArray(itemA?.box) ? itemA.box : [];
    const boxB = Array.isArray(itemB?.box) ? itemB.box : [];
    const xA = toNum(boxA[0], 0);
    const yA = toNum(boxA[1], 0);
    const xB = toNum(boxB[0], 0);
    const yB = toNum(boxB[1], 0);

    const rowBucketA = Math.round(yA / tolerance);
    const rowBucketB = Math.round(yB / tolerance);
    if (rowBucketA !== rowBucketB) {
      return rowBucketA - rowBucketB;
    }

    const nearLineThreshold = tolerance * 0.35;
    if (Math.abs(yA - yB) > nearLineThreshold) {
      return yA - yB;
    }
    if (xA !== xB) {
      return xA - xB;
    }

    const idxA = toNum(itemA?.__sourceIndex, 0);
    const idxB = toNum(itemB?.__sourceIndex, 0);
    return idxA - idxB;
  });
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeForMatch(text) {
  return (text || "")
    .normalize("NFKD")
    .replace(/[\u00AD\u200B]/g, "")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function buildNormalizedMatchIndex(text) {
  const source = String(text || "");
  let normalizedText = "";
  const indexMap = [];
  let pendingSpace = false;

  for (let sourceIndex = 0; sourceIndex < source.length; sourceIndex += 1) {
    const normalizedChunk = String(source[sourceIndex] || "")
      .normalize("NFKD")
      .replace(/[\u00AD\u200B]/g, "")
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/[\u201C\u201D]/g, '"');
    if (!normalizedChunk) continue;

    for (let chunkIndex = 0; chunkIndex < normalizedChunk.length; chunkIndex += 1) {
      const char = normalizedChunk[chunkIndex];
      if (/\s/.test(char)) {
        pendingSpace = true;
        continue;
      }
      if (pendingSpace && normalizedText.length > 0) {
        normalizedText += " ";
        indexMap.push(sourceIndex);
      }
      pendingSpace = false;
      normalizedText += char;
      indexMap.push(sourceIndex);
    }
  }

  return { text: normalizedText, indexMap };
}

function normalizedOffsetToRawOffset(indexMap, normalizedOffset, rawLength) {
  if (!Array.isArray(indexMap) || !indexMap.length) {
    return 0;
  }
  if (!Number.isFinite(normalizedOffset) || normalizedOffset <= 0) {
    return Math.max(0, Math.min(rawLength, indexMap[0]));
  }
  if (normalizedOffset >= indexMap.length) {
    return rawLength;
  }
  const mapped = indexMap[normalizedOffset];
  if (Number.isFinite(mapped)) {
    return Math.max(0, Math.min(rawLength, mapped));
  }
  return rawLength;
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
      : raw.text || raw.raw || raw.reference || "";
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

function normalizeArticleInfo(raw) {
  if (!raw || typeof raw !== "object") return null;
  const doi = normalizeDoi(raw.doi || raw.article_doi || "");
  if (!doi) return null;
  const authors = Array.isArray(raw.authors)
    ? raw.authors
        .map((author) => String(author || "").trim())
        .filter(Boolean)
    : [];
  const sourcesUsed = Array.isArray(raw.sources_used)
    ? raw.sources_used
        .map((source) => String(source || "").trim())
        .filter(Boolean)
    : [];
  const year = Number(raw.year);
  const referencesCount = Number(raw.references_count);
  const citedByCount = Number(raw.cited_by_count);
  return {
    doi,
    title: String(raw.title || "").trim(),
    authors,
    year: Number.isFinite(year) ? year : null,
    venue: String(raw.venue || "").trim(),
    source: String(raw.source || "").trim(),
    sources_used: sourcesUsed,
    references_count: Number.isFinite(referencesCount) ? referencesCount : 0,
    cited_by_count: Number.isFinite(citedByCount) ? citedByCount : 0,
    resolved: Boolean(raw.resolved || raw.title || authors.length || raw.venue),
    url: String(raw.url || `https://doi.org/${doi}`).trim(),
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

function normalizeLayerItems(items) {
  if (!Array.isArray(items)) return [];
  return items
    .map((item, index) => {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        return item;
      }
      if (item === null || item === undefined) {
        return null;
      }
      return {
        id: `layer-item-${index + 1}`,
        text: String(item),
        page: null,
        box: null,
      };
    })
    .filter(Boolean);
}

function countLayerItems(layers) {
  if (!layers || typeof layers !== "object") return 0;
  return Object.values(layers).reduce((total, list) => {
    if (!Array.isArray(list)) return total;
    return total + normalizeLayerItems(list).length;
  }, 0);
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

function collectCitationHitsForPage(pageEl, options = {}) {
  if (!pageEl) return [];
  const textLayer = pageEl.querySelector(".textLayer");
  if (!textLayer) return [];
  const { text, nodes } = buildTextLayerIndex(textLayer);
  if (!text) return [];

  const citationStyle = String(options.citationStyle || "").trim().toLowerCase();
  const maxReferenceIndex = Number(options.maxReferenceIndex);
  const hasMaxReferenceIndex =
    Number.isFinite(maxReferenceIndex) && maxReferenceIndex > 0;
  const bibliographyStartPage = Number(options.bibliographyStartPage);
  const hasBibliographyStartPage =
    Number.isFinite(bibliographyStartPage) && bibliographyStartPage > 0;
  const pageNumber = Number(pageEl.dataset.pageNumber || pageEl.getAttribute("data-page-number"));
  if (
    hasBibliographyStartPage &&
    Number.isFinite(pageNumber) &&
    pageNumber >= bibliographyStartPage
  ) {
    return [];
  }

  const pageRect = pageEl.getBoundingClientRect();
  const { text: normalizedText, indexMap } = buildNormalizedMatchIndex(text);
  if (!normalizedText || !indexMap.length) return [];

  const spansTaken = [];
  const overlaps = (start, end) => {
    for (let i = 0; i < spansTaken.length; i += 1) {
      const [s, e] = spansTaken[i];
      if (start < e && end > s) return true;
    }
    return false;
  };

  const buildHitFromMatch = (match, kind, extra = {}) => {
    const startOffset = normalizedOffsetToRawOffset(indexMap, match.index, text.length);
    let endOffset = normalizedOffsetToRawOffset(
      indexMap,
      match.index + match[0].length,
      text.length
    );
    if (endOffset <= startOffset) {
      endOffset = Math.min(text.length, startOffset + Math.max(1, match[0].length));
    }
    if (overlaps(startOffset, endOffset)) return null;
    const startNode = findNodeAtOffset(nodes, startOffset);
    const endNode = findNodeAtOffset(nodes, endOffset);
    if (!startNode || !endNode) return null;
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
    if (!rects.length) return null;
    const snippetStart = Math.max(0, startOffset - 180);
    const snippetEnd = Math.min(text.length, endOffset + 180);
    const snippet = text
      .slice(snippetStart, snippetEnd)
      .replace(/\s+/g, " ")
      .trim();
    spansTaken.push([startOffset, endOffset]);
    return {
      id: `cite-${kind}-${pageNumber}-${startOffset}`,
      page: Number.isFinite(pageNumber) ? pageNumber : null,
      label: match[0],
      kind,
      numbers: Array.isArray(extra.numbers) ? extra.numbers : [],
      snippet,
      rects,
      anchorRect: rects[0],
      ...extra,
    };
  };

  const hits = [];

  // 1) Numericas: [12], [1, 2-3].
  const numericRegex = new RegExp(INLINE_CITATION_REGEX.source, "g");
  let nm = numericRegex.exec(normalizedText);
  while (nm) {
    const parsedNumbers = parseCitationNumbers(nm[0]).filter(
      (value) => Number.isFinite(value) && value > 0
    );
    let acceptedNumbers = parsedNumbers;
    if (citationStyle === "numeric" && hasMaxReferenceIndex) {
      acceptedNumbers = acceptedNumbers.filter((value) => value <= maxReferenceIndex);
    }
    if (citationStyle === "numeric" && !acceptedNumbers.length) {
      nm = numericRegex.exec(normalizedText);
      continue;
    }
    if (acceptedNumbers.length) {
      const hit = buildHitFromMatch(nm, "numeric", { numbers: acceptedNumbers });
      if (hit) hits.push(hit);
    }
    nm = numericRegex.exec(normalizedText);
  }

  // 2) DOI desnudos. Antes que autor-anio para que no se solapen.
  const doiRegex = new RegExp(INLINE_DOI_REGEX.source, "gi");
  let dm = doiRegex.exec(normalizedText);
  while (dm) {
    const cleaned = stripDoiTrailing(dm[0]);
    if (cleaned.length >= "10.1/a".length) {
      const fakeMatch = { 0: cleaned, index: dm.index };
      const hit = buildHitFromMatch(fakeMatch, "doi", { doi: cleaned.toLowerCase() });
      if (hit) hits.push(hit);
    }
    dm = doiRegex.exec(normalizedText);
  }

  // 3) Autor-anio narrativo: "Smith et al. (2020)".
  const narrativeRegex = new RegExp(NARRATIVE_AUTHOR_YEAR_REGEX.source, "g");
  let am = narrativeRegex.exec(normalizedText);
  while (am) {
    const head = am[0].split("(", 1)[0];
    if (!looksLikeFalseAuthorHead(head)) {
      const hit = buildHitFromMatch(am, "authoryear", {
        authoryearStyle: "narrative",
        authors: head.trim(),
      });
      if (hit) hits.push(hit);
    }
    am = narrativeRegex.exec(normalizedText);
  }

  // 4) Autor-anio parentetico: "(Smith, 2020; Jones, 2021)".
  const parenRegex = new RegExp(PARENTHETICAL_AUTHOR_YEAR_REGEX.source, "g");
  let pm = parenRegex.exec(normalizedText);
  while (pm) {
    const inner = pm[0].replace(/^[(\s]+|[)\s]+$/g, "");
    if (!looksLikeFalseAuthorHead(inner)) {
      const hit = buildHitFromMatch(pm, "authoryear", {
        authoryearStyle: "parenthetical",
        authors: inner,
      });
      if (hit) hits.push(hit);
    }
    pm = parenRegex.exec(normalizedText);
  }

  hits.sort((a, b) => {
    const aTop = a.anchorRect?.top || 0;
    const bTop = b.anchorRect?.top || 0;
    if (aTop !== bTop) return aTop - bTop;
    return (a.anchorRect?.left || 0) - (b.anchorRect?.left || 0);
  });
  return hits;
}

function useHighlightedSnippet(mention, onHighlight, viewerRef) {
  useEffect(() => {
    const pageNumber = Number(mention?.page);
    if (!mention || !Number.isFinite(pageNumber)) {
      return;
    }
    let cancelled = false;
    let attempts = 0;
    let retryTimer = null;
    const maxAttempts = 14;
    const retryDelayMs = 220;

    const run = () => {
      if (cancelled) return;
      let highlightAnchor = null;
      document
        .querySelectorAll(".reader-highlight")
        .forEach((el) => el.classList.remove("reader-highlight"));
      document
        .querySelectorAll(".reader-paragraph-layer")
        .forEach((layer) => (layer.innerHTML = ""));

      const pageEl = document.querySelector(
        `.pdf-reader__page[data-page-number="${pageNumber}"]`
      );
      if (!pageEl) {
        if (attempts < maxAttempts) {
          attempts += 1;
          retryTimer = window.setTimeout(run, retryDelayMs);
        } else if (typeof onHighlight === "function") {
          onHighlight({ matched: false, page: pageNumber, anchorRect: null });
        }
        return;
      }
      const textLayer = pageEl.querySelector(".textLayer");
      if (!textLayer) {
        if (attempts < maxAttempts) {
          attempts += 1;
          retryTimer = window.setTimeout(run, retryDelayMs);
        } else if (typeof onHighlight === "function") {
          onHighlight({ matched: false, page: pageNumber, anchorRect: null });
        }
        return;
      }

      const { text, nodes } = buildTextLayerIndex(textLayer);
      if (!text) {
        if (attempts < maxAttempts) {
          attempts += 1;
          retryTimer = window.setTimeout(run, retryDelayMs);
        } else if (typeof onHighlight === "function") {
          onHighlight({ matched: false, page: pageNumber, anchorRect: null });
        }
        return;
      }
      const { text: normalizedText, indexMap: normalizedIndexMap } =
        buildNormalizedMatchIndex(text);
      if (!normalizedText || !normalizedIndexMap.length) {
        if (attempts < maxAttempts) {
          attempts += 1;
          retryTimer = window.setTimeout(run, retryDelayMs);
        } else if (typeof onHighlight === "function") {
          onHighlight({ matched: false, page: pageNumber, anchorRect: null });
        }
        return;
      }
      const highlightMode = mention.highlightMode || "snippet";
      const snippetText = String(mention.highlight_snippet || mention.snippet || "").trim();
      const referenceIndex = Number(mention.reference_index);
      let matched = false;

      const captureAnchorFromIndices = (indices) => {
        if (!indices?.length) return;
        const pageRect = pageEl.getBoundingClientRect();
        for (const idx of indices) {
          const span = nodes[idx]?.span;
          if (!span) continue;
          const rect = span.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) continue;
          highlightAnchor = {
            page: pageNumber,
            anchorRect: {
              left: Math.max(0, rect.left - pageRect.left),
              top: Math.max(0, rect.top - pageRect.top),
              width: rect.width,
              height: rect.height,
            },
          };
          return;
        }
      };

      let didScrollToParagraph = false;
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
        const lineGapThreshold = Math.max(lineHeight * 2.15, 20);
        const lineBucket = Math.max(2, Math.round(lineHeight * 0.6));
        const anchorLeft = Math.min(...matchedRects.map((rect) => rect.left));
        const anchorRight = Math.max(...matchedRects.map((rect) => rect.right));
        const anchorCenterX = (anchorLeft + anchorRight) / 2;
        const columnPadding = Math.max(lineHeight * 2.25, 56);
        const lineMap = new Map();
        nodes.forEach((node) => {
          const rect = node.span.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) return;
          const overlap =
            Math.min(rect.right, anchorRight + columnPadding) -
            Math.max(rect.left, anchorLeft - columnPadding);
          const centerX = (rect.left + rect.right) / 2;
          const nearColumn =
            overlap > 0 || Math.abs(centerX - anchorCenterX) <= columnPadding;
          if (!nearColumn) return;
          const key = Math.round(rect.top / lineBucket) * lineBucket;
          const current = lineMap.get(key) || {
            top: rect.top,
            bottom: rect.bottom,
            left: rect.left,
            right: rect.right,
          };
          current.top = Math.min(current.top, rect.top);
          current.bottom = Math.max(current.bottom, rect.bottom);
          current.left = Math.min(current.left, rect.left);
          current.right = Math.max(current.right, rect.right);
          lineMap.set(key, current);
        });
        const lines = Array.from(lineMap.values()).sort((a, b) => a.top - b.top);
        if (!lines.length) return;
        const minTop = Math.min(...matchedRects.map((rect) => rect.top));
        const maxBottom = Math.max(...matchedRects.map((rect) => rect.bottom));
        let startLine = lines.findIndex((line) => line.bottom >= minTop - 1);
        let endLine = -1;
        for (let i = lines.length - 1; i >= 0; i -= 1) {
          if (lines[i].top <= maxBottom + 1) {
            endLine = i;
            break;
          }
        }
        if (startLine === -1) startLine = 0;
        if (endLine === -1) endLine = lines.length - 1;
        const maxParagraphLines = 14;
        while (
          startLine > 0 &&
          lines[startLine].top - lines[startLine - 1].bottom <=
            lineGapThreshold &&
          endLine - (startLine - 1) + 1 <= maxParagraphLines
        ) {
          startLine -= 1;
        }
        while (
          endLine < lines.length - 1 &&
          lines[endLine + 1].top - lines[endLine].bottom <= lineGapThreshold &&
          endLine + 1 - startLine + 1 <= maxParagraphLines
        ) {
          endLine += 1;
        }
        let layer = pageEl.querySelector(".reader-paragraph-layer");
        if (!layer) {
          layer = document.createElement("div");
          layer.className = "reader-paragraph-layer";
          if (window.getComputedStyle(pageEl).position === "static") {
            pageEl.style.position = "relative";
          }
          pageEl.appendChild(layer);
        }
        layer.innerHTML = "";
        const pageRect = pageEl.getBoundingClientRect();
        const verticalPad = Math.max(1, Math.round(lineHeight * 0.08));
        const horizontalPad = 2;
        for (let i = startLine; i <= endLine; i += 1) {
          const line = lines[i];
          if (!line) continue;
          const left = Math.max(0, line.left - pageRect.left - horizontalPad);
          const top = Math.max(0, line.top - pageRect.top - verticalPad);
          const width = Math.min(
            pageRect.width - left,
            line.right - line.left + horizontalPad * 2
          );
          const height = line.bottom - line.top + verticalPad * 2;
          if (width < 2 || height < 2) continue;
          const block = document.createElement("div");
          block.className = "reader-paragraph-hit";
          block.style.left = `${left}px`;
          block.style.top = `${top}px`;
          block.style.width = `${width}px`;
          block.style.height = `${height}px`;
          layer.appendChild(block);
        }
        const firstLine = lines[startLine];
        if (firstLine) {
          highlightAnchor = {
            page: pageNumber,
            anchorRect: {
              left: Math.max(0, firstLine.left - pageRect.left),
              top: Math.max(0, firstLine.top - pageRect.top),
              width: Math.max(2, firstLine.right - firstLine.left),
              height: Math.max(2, firstLine.bottom - firstLine.top),
            },
          };
        }

        if (!didScrollToParagraph) {
          if (firstLine) {
            const paragraphTop = Math.max(
              0,
              firstLine.top - pageRect.top - verticalPad
            );
            const viewerEl = viewerRef?.current || pageEl.closest(".reader-scroll");
            if (viewerEl) {
              const viewerRect = viewerEl.getBoundingClientRect();
              const currentPageRect = pageEl.getBoundingClientRect();
              const targetTop = Math.max(
                0,
                viewerEl.scrollTop +
                  (currentPageRect.top - viewerRect.top) +
                  paragraphTop -
                  8
              );
              viewerEl.scrollTo({ top: targetTop, behavior: "smooth" });
              didScrollToParagraph = true;
            }
          }
        }
      };

      if (highlightMode === "paragraph" && Number.isFinite(referenceIndex)) {
        const regex = new RegExp(INLINE_CITATION_REGEX.source, "g");
        let match = regex.exec(normalizedText);
        while (match) {
          const numbers = parseCitationNumbers(match[0]);
          if (numbers.includes(referenceIndex)) {
            const startOffset = normalizedOffsetToRawOffset(
              normalizedIndexMap,
              match.index,
              text.length
            );
            let endOffset = normalizedOffsetToRawOffset(
              normalizedIndexMap,
              match.index + match[0].length,
              text.length
            );
            if (endOffset <= startOffset) {
              endOffset = Math.min(
                text.length,
                startOffset + Math.max(1, match[0].length)
              );
            }
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
          match = regex.exec(normalizedText);
        }
      }

      if (snippetText) {
        const normalizedSnippetText = normalizeForMatch(
          snippetText
            .replace(/^\s*\.{2,}\s*/, "")
            .replace(/\s*\.{2,}\s*$/, "")
        );
        const tokenLimit = highlightMode === "paragraph" ? 16 : HIGHLIGHT_TOKEN_LIMIT;
        const tokens = normalizedSnippetText
          ? normalizedSnippetText.split(/\s+/).slice(0, tokenLimit)
          : [];
        const pattern = tokens.map(escapeRegExp).join("\\s+");
        if (pattern) {
          try {
            const regex = new RegExp(pattern, "i");
            const match = regex.exec(normalizedText);
            if ((highlightMode === "paragraph" || !matched) && match) {
              const startOffset = normalizedOffsetToRawOffset(
                normalizedIndexMap,
                match.index,
                text.length
              );
              let endOffset = normalizedOffsetToRawOffset(
                normalizedIndexMap,
                match.index + match[0].length,
                text.length
              );
              if (endOffset <= startOffset) {
                endOffset = Math.min(
                  text.length,
                  startOffset + Math.max(1, match[0].length)
                );
              }
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
                captureAnchorFromIndices(matchedIndices);
                matchedIndices.forEach((idx) => nodes[idx].span.classList.add("reader-highlight"));
              }
            }
          } catch (err) {
            matched = false;
          }
        }
      }

      if (snippetText && (!matched || highlightMode === "paragraph")) {
        const normalized = normalizeForMatch(snippetText).toLowerCase();
        const keywords = normalized
          .split(" ")
          .filter((word) => word.length > 3)
          .slice(0, 8);
        const matchedIndices = [];
        nodes.forEach((node, index) => {
          const spanText = normalizeForMatch(node.span.textContent || "").toLowerCase();
          if (keywords.some((word) => spanText.includes(word))) {
            matched = true;
            matchedIndices.push(index);
          }
        });
        if (matchedIndices.length) {
          if (highlightMode === "paragraph") {
            applyParagraphHighlight(matchedIndices);
          } else {
            captureAnchorFromIndices(matchedIndices);
            matchedIndices.forEach((idx) => nodes[idx].span.classList.add("reader-highlight"));
          }
        }
      }

      if (typeof onHighlight === "function") {
        onHighlight({
          matched,
          page: pageNumber,
          anchorRect: highlightAnchor?.anchorRect || null,
        });
      }
    };

    retryTimer = window.setTimeout(run, 180);
    return () => {
      cancelled = true;
      if (retryTimer) {
        window.clearTimeout(retryTimer);
      }
    };
  }, [mention, onHighlight, viewerRef]);
}

function getPageOverlayAnchorRect(pageEl) {
  if (!pageEl || typeof pageEl.querySelector !== "function") {
    return {
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    };
  }

  const selectors = [
    ".react-pdf__Page__canvas",
    ".react-pdf__Page canvas",
    ".react-pdf__Page__textContent",
  ];

  let anchorEl = null;
  for (let index = 0; index < selectors.length; index += 1) {
    const candidate = pageEl.querySelector(selectors[index]);
    if (candidate) {
      anchorEl = candidate;
      break;
    }
  }

  const pageRect = pageEl.getBoundingClientRect();
  const fallbackWidth = pageEl.clientWidth || pageRect.width || 0;
  const fallbackHeight = pageEl.clientHeight || pageRect.height || 0;

  if (!anchorEl || typeof anchorEl.getBoundingClientRect !== "function") {
    return {
      left: 0,
      top: 0,
      width: fallbackWidth,
      height: fallbackHeight,
    };
  }

  const anchorRect = anchorEl.getBoundingClientRect();
  const left = anchorRect.left - pageRect.left;
  const top = anchorRect.top - pageRect.top;
  const width = anchorRect.width || fallbackWidth;
  const height = anchorRect.height || fallbackHeight;

  return {
    left: Number.isFinite(left) ? left : 0,
    top: Number.isFinite(top) ? top : 0,
    width: Number.isFinite(width) ? width : fallbackWidth,
    height: Number.isFinite(height) ? height : fallbackHeight,
  };
}

function getPrimaryPdfPageElements(viewerEl) {
  if (!viewerEl || typeof viewerEl.querySelectorAll !== "function") {
    return [];
  }

  const pageNodes = Array.from(
    viewerEl.querySelectorAll(".pdf-reader__page[data-page-number]")
  );
  const byPageNumber = new Map();

  pageNodes.forEach((pageEl) => {
    const rawPageNumber = Number(
      pageEl.dataset.pageNumber || pageEl.getAttribute("data-page-number")
    );
    if (!Number.isFinite(rawPageNumber) || rawPageNumber <= 0) {
      return;
    }
    const area = Math.max(0, pageEl.clientWidth) * Math.max(0, pageEl.clientHeight);
    const prev = byPageNumber.get(rawPageNumber);
    if (!prev || area >= prev.area) {
      byPageNumber.set(rawPageNumber, { pageEl, area });
    }
  });

  return Array.from(byPageNumber.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([pageNumber, entry]) => ({
      pageNumber,
      pageIndex: pageNumber - 1,
      pageEl: entry.pageEl,
    }));
}

function collectVisibleTextRectsNormalized(pageEl, anchorRect) {
  if (!pageEl || !anchorRect) return [];
  const textLayer =
    pageEl.querySelector(".textLayer") ||
    pageEl.querySelector(".react-pdf__Page__textContent");
  if (!textLayer) return [];

  const anchorWidth = Number(anchorRect.width);
  const anchorHeight = Number(anchorRect.height);
  if (!Number.isFinite(anchorWidth) || !Number.isFinite(anchorHeight)) return [];
  if (anchorWidth <= 0 || anchorHeight <= 0) return [];

  const pageRect = pageEl.getBoundingClientRect();
  const anchorLeft = pageRect.left + Number(anchorRect.left || 0);
  const anchorTop = pageRect.top + Number(anchorRect.top || 0);
  const spans = Array.from(textLayer.querySelectorAll("span"));
  const rects = [];

  spans.forEach((span) => {
    if (!span) return;
    const text = String(span.textContent || "").trim();
    if (!text) return;
    const rect = span.getBoundingClientRect();
    if (rect.width < 0.8 || rect.height < 0.8) return;

    const x = (rect.left - anchorLeft) / anchorWidth;
    const y = (rect.top - anchorTop) / anchorHeight;
    const width = rect.width / anchorWidth;
    const height = rect.height / anchorHeight;
    if (![x, y, width, height].every((value) => Number.isFinite(value))) return;
    if (width <= 0 || height <= 0) return;

    const clampedX = Math.max(0, Math.min(1, x));
    const clampedY = Math.max(0, Math.min(1, y));
    const clampedWidth = Math.max(0, Math.min(1 - clampedX, width));
    const clampedHeight = Math.max(0, Math.min(1 - clampedY, height));
    if (clampedWidth <= 0 || clampedHeight <= 0) return;
    rects.push({
      x: clampedX,
      y: clampedY,
      width: clampedWidth,
      height: clampedHeight,
    });
  });

  return rects;
}

function buildVisibleTextRectBuckets(rects, bucketSize = 0.02) {
  const safeBucket = Math.max(0.005, Number(bucketSize) || 0.02);
  const buckets = new Map();
  rects.forEach((rect) => {
    const start = Math.max(0, Math.floor(rect.y / safeBucket));
    const end = Math.max(start, Math.floor((rect.y + rect.height) / safeBucket));
    for (let index = start; index <= end; index += 1) {
      const list = buckets.get(index) || [];
      list.push(rect);
      buckets.set(index, list);
    }
  });
  return { buckets, bucketSize: safeBucket };
}

function isOverlayCenterOnVisibleText(item, rectBuckets, tolerance = 0.0035) {
  const cx = Number(item?.x) + Number(item?.width) / 2;
  const cy = Number(item?.y) + Number(item?.height) / 2;
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return false;
  const safeTolerance = Math.max(0, Number(tolerance) || 0);
  const bucketSize = rectBuckets?.bucketSize || 0.02;
  const buckets = rectBuckets?.buckets;
  if (!(buckets instanceof Map) || buckets.size === 0) return true;
  const bucketIndex = Math.max(0, Math.floor(cy / bucketSize));

  const candidates = [
    ...(buckets.get(bucketIndex - 1) || []),
    ...(buckets.get(bucketIndex) || []),
    ...(buckets.get(bucketIndex + 1) || []),
  ];
  if (!candidates.length) return false;

  return candidates.some((rect) => {
    const left = rect.x - safeTolerance;
    const right = rect.x + rect.width + safeTolerance;
    const top = rect.y - safeTolerance;
    const bottom = rect.y + rect.height + safeTolerance;
    return cx >= left && cx <= right && cy >= top && cy <= bottom;
  });
}

function useReaderV2Overlay(
  viewerRef,
  readerV2Data,
  readerV2Layer,
  readerV2LayerItems,
  showReaderV2,
  readerV2Opacity,
  hoveredItemId,
  selectedItemId,
  onHoverItemChange,
  onSelectItem
) {
  const hoveredItemIdRef = useRef(hoveredItemId);
  const selectedItemIdRef = useRef(selectedItemId);

  useEffect(() => {
    hoveredItemIdRef.current = hoveredItemId;
    selectedItemIdRef.current = selectedItemId;
  }, [hoveredItemId, selectedItemId]);

  useEffect(() => {
    const viewerEl = viewerRef?.current;
    if (!viewerEl) return;

    const removeOverlays = () => {
      viewerEl
        .querySelectorAll(".reader-v2-overlay")
        .forEach((overlay) => overlay.remove());
    };

    const pagesSource = Array.isArray(readerV2Data?.pages) ? readerV2Data.pages : [];
    const selectedLayerItems = Array.isArray(readerV2LayerItems)
      ? readerV2LayerItems
      : [];

    if (!showReaderV2 || selectedLayerItems.length === 0) {
      removeOverlays();
      return;
    }

    const pageMetaByIndex = new Map();
    pagesSource.forEach((page, index) => {
      const rawPage = Number(page?.page);
      const pageIndex = Number.isFinite(rawPage) ? rawPage : index;
      pageMetaByIndex.set(pageIndex, {
        width: Number(page?.width) || 0,
        height: Number(page?.height) || 0,
      });
    });

    const normalizeBox = (box, pageMeta) => {
      if (!Array.isArray(box) || box.length < 4) return null;
      let x = Number(box[0]);
      let y = Number(box[1]);
      let width = Number(box[2]);
      let height = Number(box[3]);
      if (![x, y, width, height].every((value) => Number.isFinite(value))) return null;
      if (width <= 0 || height <= 0) return null;

      const looksNormalized =
        x >= 0 &&
        y >= 0 &&
        width > 0 &&
        height > 0 &&
        x <= 1.05 &&
        y <= 1.05 &&
        width <= 1.05 &&
        height <= 1.05;

      if (!looksNormalized) {
        const pageWidth = Number(pageMeta?.width);
        const pageHeight = Number(pageMeta?.height);
        if (
          !Number.isFinite(pageWidth) ||
          !Number.isFinite(pageHeight) ||
          pageWidth <= 0 ||
          pageHeight <= 0
        ) {
          return null;
        }
        x /= pageWidth;
        y /= pageHeight;
        width /= pageWidth;
        height /= pageHeight;
      }

      const clampedX = Math.max(0, Math.min(1, x));
      const clampedY = Math.max(0, Math.min(1, y));
      const clampedWidth = Math.max(0, Math.min(1 - clampedX, width));
      const clampedHeight = Math.max(0, Math.min(1 - clampedY, height));
      if (clampedWidth <= 0 || clampedHeight <= 0) return null;

      return {
        x: clampedX,
        y: clampedY,
        width: clampedWidth,
        height: clampedHeight,
      };
    };

    const itemsByPage = new Map();
    selectedLayerItems.forEach((item, index) => {
      const pageIndex = Number(item?.page);
      if (!Number.isFinite(pageIndex) || pageIndex < 0) return;
      const normalized = normalizeBox(item?.box, pageMetaByIndex.get(pageIndex));
      if (!normalized) return;
      const adjusted = getAdjustedBox(normalized, readerV2Layer);
      if (!adjusted) return;
      const sanitizedType = String(item?.type || "item")
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, "-");
      const sourceIndex = Number(item?.__sourceIndex);
      const fallbackIndex = Number.isFinite(sourceIndex) ? sourceIndex : index;
      const normalizedId = String(
        item?.__v2id || getReaderV2ItemId(item, fallbackIndex, readerV2Layer || "layer")
      );
      const sourceId = String(
        item?.__v2sourceId ||
          getReaderV2SourceId(item, fallbackIndex, readerV2Layer || "layer")
      );
      const list = itemsByPage.get(pageIndex) || [];
      if (list.some((entry) => entry.id === normalizedId)) {
        return;
      }
      list.push({
        ...adjusted,
        id: normalizedId,
        sourceId,
        text: String(item?.text || ""),
        typeClass: sanitizedType || "item",
      });
      itemsByPage.set(pageIndex, list);
    });

    let rafId = null;
    const rawOpacity = Number(readerV2Opacity);
    const opacity = Number.isFinite(rawOpacity)
      ? Math.max(0, Math.min(1, rawOpacity))
      : 1;
    const shouldFilterByVisibleText =
      String(readerV2Layer || "").toLowerCase() === "tokens";
    const render = () => {
      rafId = null;
      const primaryPages = getPrimaryPdfPageElements(viewerEl);
      const primaryPageSet = new Set(primaryPages.map((entry) => entry.pageEl));
      viewerEl.querySelectorAll(".reader-v2-overlay").forEach((overlayEl) => {
        const hostPage = overlayEl.closest(".pdf-reader__page");
        if (!hostPage || !primaryPageSet.has(hostPage)) {
          overlayEl.remove();
        }
      });

      primaryPages.forEach(({ pageIndex, pageEl }) => {
        const pageItems = pageIndex >= 0 ? itemsByPage.get(pageIndex) || [] : [];
        const existingOverlays = Array.from(
          pageEl.querySelectorAll(".reader-v2-overlay")
        );
        let overlay = existingOverlays.length ? existingOverlays[0] : null;
        if (existingOverlays.length > 1) {
          existingOverlays.slice(1).forEach((extraOverlay) => extraOverlay.remove());
        }

        if (!pageItems.length) {
          if (overlay) {
            overlay.remove();
          }
          return;
        }

        if (!overlay) {
          overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          overlay.classList.add("reader-v2-overlay");
          overlay.setAttribute("viewBox", "0 0 1 1");
          overlay.setAttribute("preserveAspectRatio", "none");
          if (window.getComputedStyle(pageEl).position === "static") {
            pageEl.style.position = "relative";
          }
          pageEl.appendChild(overlay);
        }

        const anchorRect = getPageOverlayAnchorRect(pageEl);
        overlay.style.left = `${Math.max(0, anchorRect.left)}px`;
        overlay.style.top = `${Math.max(0, anchorRect.top)}px`;
        overlay.style.right = "auto";
        overlay.style.bottom = "auto";
        overlay.style.width = `${Math.max(0, anchorRect.width)}px`;
        overlay.style.height = `${Math.max(0, anchorRect.height)}px`;
        overlay.style.opacity = `${opacity}`;

        let filteredPageItems = pageItems;
        if (shouldFilterByVisibleText) {
          const visibleTextRects = collectVisibleTextRectsNormalized(pageEl, anchorRect);
          if (visibleTextRects.length) {
            const rectBuckets = buildVisibleTextRectBuckets(visibleTextRects);
            filteredPageItems = pageItems.filter((item) =>
              isOverlayCenterOnVisibleText(item, rectBuckets)
            );
          }
        }

        if (!filteredPageItems.length) {
          overlay.remove();
          return;
        }

        while (overlay.firstChild) {
          overlay.removeChild(overlay.firstChild);
        }

        filteredPageItems.forEach((entry) => {
          const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          const classNames = [
            "reader-v2-box",
            `reader-v2-box--${entry.typeClass}`,
          ];
          if (entry.sourceId === hoveredItemIdRef.current) {
            classNames.push("is-hovered");
          }
          if (entry.sourceId === selectedItemIdRef.current) {
            classNames.push("is-selected");
          }
          rect.setAttribute("class", classNames.join(" "));
          rect.setAttribute("data-v2-id", entry.id);
          rect.setAttribute("data-v2-source-id", entry.sourceId);
          rect.setAttribute("x", `${entry.x}`);
          rect.setAttribute("y", `${entry.y}`);
          rect.setAttribute("width", `${entry.width}`);
          rect.setAttribute("height", `${entry.height}`);
          rect.setAttribute("title", entry.text || entry.id);
          rect.addEventListener("mouseenter", () => {
            if (typeof onHoverItemChange === "function") {
              onHoverItemChange(entry.sourceId);
            }
          });
          rect.addEventListener("mouseleave", () => {
            if (typeof onHoverItemChange === "function") {
              onHoverItemChange(null);
            }
          });
          rect.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (typeof onSelectItem === "function") {
              onSelectItem(entry.sourceId);
            }
          });
          overlay.appendChild(rect);
        });
      });
    };

    const schedule = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(render);
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
      removeOverlays();
    };
  }, [
    viewerRef,
    readerV2Data,
    readerV2Layer,
    readerV2LayerItems,
    showReaderV2,
    readerV2Opacity,
    onHoverItemChange,
    onSelectItem,
  ]);

  useEffect(() => {
    const viewerEl = viewerRef?.current;
    if (!viewerEl) return;

    const boxes = viewerEl.querySelectorAll(".reader-v2-box");
    boxes.forEach((boxEl) => {
      const sourceId =
        boxEl.getAttribute("data-v2-source-id") ||
        boxEl.getAttribute("data-v2-id");
      const isHovered = Boolean(hoveredItemId) && sourceId === hoveredItemId;
      const isSelected = Boolean(selectedItemId) && sourceId === selectedItemId;
      boxEl.classList.toggle("is-hovered", isHovered);
      boxEl.classList.toggle("is-selected", isSelected);
    });
  }, [
    viewerRef,
    hoveredItemId,
    selectedItemId,
    readerV2Layer,
    readerV2Data,
    readerV2LayerItems,
    showReaderV2,
  ]);
}

// ── Reference Debug Overlay ──────────────────────────────────────────────────

const REF_DEBUG_STEP_COLORS = Object.freeze({
  assign_column_ids:                    { fill: "rgba(148,163,184,0.18)", stroke: "rgba(100,116,139,0.85)" },
  detect_page_column_split:             { fill: "rgba(245,158,11,0.18)",  stroke: "rgba(217,119,6,0.90)"  },
  detect_reference_heading_candidates: { fill: "rgba(167,139,250,0.22)", stroke: "rgba(124,58,237,0.88)" },
  selected_heading:                     { fill: "rgba(124,58,237,0.28)",  stroke: "rgba(109,40,217,0.95)" },
  bibliography_segments:                { fill: "rgba(56,189,248,0.20)",  stroke: "rgba(14,165,233,0.88)" },
  rows_in_bibliography_zone:            { fill: "rgba(74,222,128,0.18)",  stroke: "rgba(34,197,94,0.85)"  },
  reference_anchors:                    { fill: "rgba(251,146,60,0.22)",  stroke: "rgba(234,88,12,0.90)"  },
  reference_block_rows:                 { fill: "rgba(244,114,182,0.18)", stroke: "rgba(219,39,119,0.85)" },
  accepted_references:                  { fill: "rgba(52,211,153,0.22)",  stroke: "rgba(16,185,129,0.90)" },
  rejected_references:                  { fill: "rgba(248,113,113,0.22)", stroke: "rgba(239,68,68,0.90)"  },
});

const REF_DEBUG_STEP_DEFAULT_COLOR = { fill: "rgba(99,102,241,0.18)", stroke: "rgba(79,70,229,0.85)" };

function useRefDebugOverlay(
  viewerRef,
  readerV2Data,
  refDebugSteps,
  activeRefDebugKeys,
  showRefDebug,
  refDebugOpacity,
) {
  useEffect(() => {
    const viewerEl = viewerRef?.current;
    if (!viewerEl) return;

    const OVERLAY_CLASS = "reader-ref-debug-overlay";

    const removeOverlays = () => {
      viewerEl.querySelectorAll(`.${OVERLAY_CLASS}`).forEach((el) => el.remove());
    };

    const activeSteps = (refDebugSteps || []).filter(
      (step) => activeRefDebugKeys.has(step.key)
    );

    if (!showRefDebug || activeSteps.length === 0) {
      removeOverlays();
      return;
    }

    const pagesSource = Array.isArray(readerV2Data?.pages) ? readerV2Data.pages : [];
    const pageMetaByIndex = new Map();
    pagesSource.forEach((page, index) => {
      const rawPage = Number(page?.page);
      const pageIndex = Number.isFinite(rawPage) ? rawPage : index;
      pageMetaByIndex.set(pageIndex, {
        width: Number(page?.width) || 0,
        height: Number(page?.height) || 0,
      });
    });

    const normalizeBox = (box, pageMeta) => {
      if (!Array.isArray(box) || box.length < 4) return null;
      let x = Number(box[0]), y = Number(box[1]);
      let width = Number(box[2]), height = Number(box[3]);
      if (![x, y, width, height].every((v) => Number.isFinite(v))) return null;
      if (width <= 0 || height <= 0) return null;
      const looksNormalized = x >= 0 && y >= 0 && x <= 1.05 && y <= 1.05 && width <= 1.05 && height <= 1.05;
      if (!looksNormalized) {
        const pw = Number(pageMeta?.width), ph = Number(pageMeta?.height);
        if (!Number.isFinite(pw) || !Number.isFinite(ph) || pw <= 0 || ph <= 0) return null;
        x /= pw; y /= ph; width /= pw; height /= ph;
      }
      const cx = Math.max(0, Math.min(1, x));
      const cy = Math.max(0, Math.min(1, y));
      const cw = Math.max(0, Math.min(1 - cx, width));
      const ch = Math.max(0, Math.min(1 - cy, height));
      if (cw <= 0 || ch <= 0) return null;
      return { x: cx, y: cy, width: cw, height: ch };
    };

    // Build per-page render entries: { kind, box/x, color, stepKey, label }
    const entriesByPage = new Map();

    for (const step of activeSteps) {
      const color = REF_DEBUG_STEP_COLORS[step.key] || REF_DEBUG_STEP_DEFAULT_COLOR;
      const kind = step.kind || "boxes";

      for (const item of (step.items || [])) {
        const pageIndex = Number(item?.page);
        if (!Number.isFinite(pageIndex) || pageIndex < 0) continue;
        const pageMeta = pageMetaByIndex.get(pageIndex);
        const list = entriesByPage.get(pageIndex) || [];

        if (kind === "vertical_guides") {
          const rawX = Number(item?.x);
          if (!Number.isFinite(rawX)) continue;
          list.push({ kind: "guide", x: rawX, color, stepKey: step.key, label: String(item?.label || "") });
        } else {
          const normalized = normalizeBox(item?.box, pageMeta);
          if (!normalized) continue;
          list.push({ kind: "box", ...normalized, color, stepKey: step.key, label: String(item?.label || "") });
        }

        entriesByPage.set(pageIndex, list);
      }
    }

    let rafId = null;
    const opacity = Math.max(0, Math.min(1, Number(refDebugOpacity) || 0.75));

    const render = () => {
      rafId = null;
      const primaryPages = getPrimaryPdfPageElements(viewerEl);
      const primaryPageSet = new Set(primaryPages.map((e) => e.pageEl));

      viewerEl.querySelectorAll(`.${OVERLAY_CLASS}`).forEach((overlayEl) => {
        const hostPage = overlayEl.closest(".pdf-reader__page");
        if (!hostPage || !primaryPageSet.has(hostPage)) overlayEl.remove();
      });

      primaryPages.forEach(({ pageIndex, pageEl }) => {
        const pageEntries = pageIndex >= 0 ? (entriesByPage.get(pageIndex) || []) : [];
        const existingOverlays = Array.from(pageEl.querySelectorAll(`.${OVERLAY_CLASS}`));
        let overlay = existingOverlays.length ? existingOverlays[0] : null;
        existingOverlays.slice(1).forEach((e) => e.remove());

        if (!pageEntries.length) {
          if (overlay) overlay.remove();
          return;
        }

        if (!overlay) {
          overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          overlay.classList.add(OVERLAY_CLASS);
          overlay.setAttribute("viewBox", "0 0 1 1");
          overlay.setAttribute("preserveAspectRatio", "none");
          if (window.getComputedStyle(pageEl).position === "static") {
            pageEl.style.position = "relative";
          }
          pageEl.appendChild(overlay);
        }

        const anchorRect = getPageOverlayAnchorRect(pageEl);
        overlay.style.left = `${Math.max(0, anchorRect.left)}px`;
        overlay.style.top = `${Math.max(0, anchorRect.top)}px`;
        overlay.style.right = "auto";
        overlay.style.bottom = "auto";
        overlay.style.width = `${Math.max(0, anchorRect.width)}px`;
        overlay.style.height = `${Math.max(0, anchorRect.height)}px`;
        overlay.style.opacity = `${opacity}`;

        while (overlay.firstChild) overlay.removeChild(overlay.firstChild);

        for (const entry of pageEntries) {
          if (entry.kind === "guide") {
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            line.setAttribute("x1", `${entry.x}`);
            line.setAttribute("y1", "0");
            line.setAttribute("x2", `${entry.x}`);
            line.setAttribute("y2", "1");
            line.setAttribute("stroke", entry.color.stroke);
            line.setAttribute("stroke-width", "0.002");
            line.setAttribute("stroke-dasharray", "0.008 0.004");
            line.setAttribute("vector-effect", "non-scaling-stroke");
            if (entry.label) line.setAttribute("title", entry.label);
            overlay.appendChild(line);
          } else {
            const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
            rect.setAttribute("x", `${entry.x}`);
            rect.setAttribute("y", `${entry.y}`);
            rect.setAttribute("width", `${entry.width}`);
            rect.setAttribute("height", `${entry.height}`);
            rect.setAttribute("fill", entry.color.fill);
            rect.setAttribute("stroke", entry.color.stroke);
            rect.setAttribute("stroke-width", "0.003");
            rect.setAttribute("vector-effect", "non-scaling-stroke");
            if (entry.label) rect.setAttribute("title", entry.label);
            overlay.appendChild(rect);
          }
        }
      });
    };

    const schedule = () => { if (rafId) return; rafId = window.requestAnimationFrame(render); };
    const mutationObserver = new MutationObserver(schedule);
    mutationObserver.observe(viewerEl, { childList: true, subtree: true });
    const resizeObserver = new ResizeObserver(schedule);
    resizeObserver.observe(viewerEl);
    window.addEventListener("resize", schedule);
    schedule();

    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener("resize", schedule);
      removeOverlays();
    };
  }, [viewerRef, readerV2Data, refDebugSteps, activeRefDebugKeys, showRefDebug, refDebugOpacity]);
}

// ────────────────────────────────────────────────────────────────────────────

function useReferencesOverlay(
  viewerRef,
  {
    visible,
    items,
    selectedReferenceId,
    hoveredReferenceId,
    selectedCitationId,
    hoveredCitationId,
    onHoverItem,
    onSelectItem,
  }
) {
  const selectedReferenceIdRef = useRef(selectedReferenceId);
  const hoveredReferenceIdRef = useRef(hoveredReferenceId);
  const selectedCitationIdRef = useRef(selectedCitationId);
  const hoveredCitationIdRef = useRef(hoveredCitationId);

  useEffect(() => {
    selectedReferenceIdRef.current = selectedReferenceId;
    hoveredReferenceIdRef.current = hoveredReferenceId;
    selectedCitationIdRef.current = selectedCitationId;
    hoveredCitationIdRef.current = hoveredCitationId;
  }, [
    selectedReferenceId,
    hoveredReferenceId,
    selectedCitationId,
    hoveredCitationId,
  ]);

  useEffect(() => {
    const viewerEl = viewerRef?.current;
    if (!viewerEl) return;

    const removeOverlays = () => {
      viewerEl
        .querySelectorAll(".reader-ref-overlay")
        .forEach((overlay) => overlay.remove());
    };

    if (!visible) {
      removeOverlays();
      return;
    }

    const overlayItems = Array.isArray(items) ? items : [];
    const itemsByPage = new Map();
    overlayItems.forEach((item, index) => {
      const page = normalizeOverlayPage(item?.page);
      const box = normalizeOverlayBox(item?.box);
      if (page === null || !box) return;
      const itemId = String(item?.id || `ref-overlay-${index}`);
      const refId = String(item?.ref_id || "");
      const itemType = String(item?.item_type || "entry")
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, "-");
      const list = itemsByPage.get(page) || [];
      list.push({
        id: itemId,
        refId,
        itemType,
        box,
        text: String(item?.text || ""),
      });
      itemsByPage.set(page, list);
    });

    let rafId = null;
    const render = () => {
      rafId = null;
      const pageEls = viewerEl.querySelectorAll(".pdf-reader__page");
      pageEls.forEach((pageEl) => {
        const pageNumber = Number(
          pageEl.dataset.pageNumber || pageEl.getAttribute("data-page-number")
        );
        const pageIndex = Number.isFinite(pageNumber) ? pageNumber - 1 : -1;
        const pageItems = pageIndex >= 0 ? itemsByPage.get(pageIndex) || [] : [];
        let overlay = pageEl.querySelector(".reader-ref-overlay");

        if (!pageItems.length) {
          if (overlay) overlay.remove();
          return;
        }

        if (!overlay) {
          overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          overlay.classList.add("reader-ref-overlay");
          overlay.setAttribute("viewBox", "0 0 1 1");
          overlay.setAttribute("preserveAspectRatio", "none");
          if (window.getComputedStyle(pageEl).position === "static") {
            pageEl.style.position = "relative";
          }
          pageEl.appendChild(overlay);
        }

        while (overlay.firstChild) {
          overlay.removeChild(overlay.firstChild);
        }

        pageItems.forEach((entry) => {
          const selectedRefId = String(selectedReferenceIdRef.current || "");
          if (!selectedRefId || entry.refId !== selectedRefId) {
            return;
          }
          const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          const isSelectedRef = true;
          const isReferenceEntry = entry.itemType === "reference-entry";
          const isCitationMention = entry.itemType === "citation-mention";
          const isCitationContext = entry.itemType === "citation-context";
          const isSelectedCitation =
            Boolean(selectedCitationIdRef.current) &&
            entry.id === selectedCitationIdRef.current;
          const isHoveredCitation =
            Boolean(hoveredCitationIdRef.current) &&
            entry.id === hoveredCitationIdRef.current;

          const classNames = [
            "reader-ref-box",
            `reader-ref-box--${entry.itemType}`,
          ];
          if (isHoveredCitation) classNames.push("is-hovered");
          if (isSelectedRef) {
            if (isCitationContext) {
              classNames.push("is-selected-context");
            } else if (isCitationMention) {
              classNames.push("is-selected-mention");
            } else if (isReferenceEntry) {
              classNames.push("is-selected-reference");
            } else {
              classNames.push("is-selected");
            }
          }
          if (isSelectedCitation) classNames.push("is-selected-citation");

          rect.setAttribute("class", classNames.join(" "));
          rect.setAttribute("data-ref-item-id", entry.id);
          rect.setAttribute("x", `${entry.box[0]}`);
          rect.setAttribute("y", `${entry.box[1]}`);
          rect.setAttribute("width", `${entry.box[2]}`);
          rect.setAttribute("height", `${entry.box[3]}`);
          rect.setAttribute("title", entry.text || entry.id);
          rect.addEventListener("mouseenter", () => {
            if (typeof onHoverItem === "function") {
              onHoverItem(entry);
            }
          });
          rect.addEventListener("mouseleave", () => {
            if (typeof onHoverItem === "function") {
              onHoverItem(null);
            }
          });
          rect.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (typeof onSelectItem === "function") {
              onSelectItem(entry);
            }
          });
          overlay.appendChild(rect);
        });
      });
    };

    const schedule = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(render);
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
      removeOverlays();
    };
  }, [
    viewerRef,
    visible,
    items,
    onHoverItem,
    onSelectItem,
  ]);
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

function SelectionEvidenceButton({ viewerRef, evidenceUrl }) {
  const [status, setStatus] = useState({ tone: "idle", text: "" });
  const [saving, setSaving] = useState(false);

  if (!evidenceUrl) return null;

  const saveSelection = async () => {
    const payload = getReaderSelectionPayload(viewerRef?.current);
    if (!payload?.text) {
      setStatus({ tone: "warning", text: "Selecciona texto del PDF primero." });
      return;
    }
    setSaving(true);
    setStatus({ tone: "idle", text: "" });
    try {
      const response = await fetch(evidenceUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookieValue("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
          source: "reader_selection",
          article: "citing",
          kind: "pdf_selection",
          text: payload.text,
          page: payload.page,
          boxes: payload.boxes,
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data?.success) {
        setStatus({ tone: "error", text: "No se pudo guardar la evidencia." });
        return;
      }
      window.getSelection?.().removeAllRanges?.();
      setStatus({ tone: "success", text: "Evidencia guardada." });
    } catch (err) {
      setStatus({ tone: "error", text: "Error de red al guardar." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="reader-toolbar-group reader-evidence-toolbar">
      <button
        type="button"
        className="reader-tool-btn"
        onClick={saveSelection}
        disabled={saving}
      >
        {saving ? "Guardando..." : "Usar como evidencia"}
      </button>
      {status.text && (
        <span className={`reader-selection-status is-${status.tone}`}>
          {status.text}
        </span>
      )}
    </div>
  );
}

function PdfPages() {
  const { numPages } = React.useContext(DocumentContext);
  if (!numPages) {
    return <div className="reader-loading">Cargando PDF...</div>;
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

function PdfViewer({
  pdfUrl,
  evidenceUrl,
  selectedMention,
  onHighlight,
  viewerRef,
  readerV2Data,
  readerV2Layer,
  readerV2LayerItems,
  showReaderV2,
  readerV2Opacity,
  hoveredItemId,
  selectedItemId,
  onHoverItemChange,
  onSelectItem,
  referenceOverlayVisible,
  referenceOverlayItems,
  selectedReferenceId,
  hoveredReferenceId,
  selectedCitationId,
  hoveredCitationId,
  onReferenceOverlayHover,
  onReferenceOverlaySelect,
  refDebugSteps,
  activeRefDebugKeys,
  showRefDebug,
  refDebugOpacity,
}) {
  useHighlightedSnippet(selectedMention, onHighlight, viewerRef);
  useReaderV2Overlay(
    viewerRef,
    readerV2Data,
    readerV2Layer,
    readerV2LayerItems,
    showReaderV2,
    readerV2Opacity,
    hoveredItemId,
    selectedItemId,
    onHoverItemChange,
    onSelectItem
  );
  useReferencesOverlay(viewerRef, {
    visible: referenceOverlayVisible,
    items: referenceOverlayItems,
    selectedReferenceId,
    hoveredReferenceId,
    selectedCitationId,
    hoveredCitationId,
    onHoverItem: onReferenceOverlayHover,
    onSelectItem: onReferenceOverlaySelect,
  });
  useRefDebugOverlay(
    viewerRef,
    readerV2Data,
    refDebugSteps,
    activeRefDebugKeys,
    showRefDebug,
    refDebugOpacity,
  );

  if (!pdfUrl) {
    return (
      <div className="reader-empty">
        No hay PDF cargado. Selecciona un PDF en la pestaña "Extraer".
      </div>
    );
  }

  return (
    <div className="reader-viewer">
      <ContextProvider>
        <ScrollRootBinder viewerRef={viewerRef} />
        <div className="reader-toolbar">
          <ZoomControls />
          <PageNavigator viewerRef={viewerRef} />
          <SelectionEvidenceButton viewerRef={viewerRef} evidenceUrl={evidenceUrl} />
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
  evidenceUrl = "",
  reportOriginalDoi = "",
  reportIncorrectDoi = "",
  previewFile,
  previewSnippets = [],
  previewStats = null,
  previewReferences = [],
  previewEnrichment = null,
  previewArticleInfo = null,
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
  const [referencesVisualData, setReferencesVisualData] = useState({
    references: [],
    citations: [],
    contexts: [],
    citation_style: "",
    max_reference_index: null,
    bibliography_start_page: null,
  });
  const [stats, setStats] = useState(previewStats || null);
  const [activeTab, setActiveTab] = useState("extract");
  const [snippetQuery, setSnippetQuery] = useState("");
  const [referenceQuery, setReferenceQuery] = useState("");
  const [snippetFilter, setSnippetFilter] = useState("all");
  const [referenceFilter, setReferenceFilter] = useState("all");
  const [selectedSnippet, setSelectedSnippet] = useState(null);
  const [highlightNotice, setHighlightNotice] = useState("");
  const [selectedSnippetAnchor, setSelectedSnippetAnchor] = useState(null);
  const [selectedSnippetPopoverStyle, setSelectedSnippetPopoverStyle] = useState(
    null
  );
  const [activeReferenceKey, setActiveReferenceKey] = useState("");
  const [activeCitation, setActiveCitation] = useState(null);
  const [citationPopoverStyle, setCitationPopoverStyle] = useState(null);
  const [activeReferenceId, setActiveReferenceId] = useState(null);
  const [highlightReferenceId, setHighlightReferenceId] = useState(null);
  const [inlineCitations, setInlineCitations] = useState([]);
  const [popoverExpanded, setPopoverExpanded] = useState(false);
  const [selectedReferenceId, setSelectedReferenceId] = useState("");
  const [hoveredReferenceId, setHoveredReferenceId] = useState("");
  const [selectedCitationId, setSelectedCitationId] = useState("");
  const [hoveredCitationId, setHoveredCitationId] = useState("");
  const [extractStatus, setExtractStatus] = useState({
    loading: false,
    error: "",
    message: "",
    hint: "",
    tone: "idle",
  });
  const [extractProgress, setExtractProgress] = useState({
    value: 0,
    label: "",
  });
  const [articleDoiInput, setArticleDoiInput] = useState(
    String(reportOriginalDoi || "").trim()
  );
  const [debugReferenceDetection, setDebugReferenceDetection] = useState(false);
  const [extractEnrichment, setExtractEnrichment] = useState(
    previewEnrichment && typeof previewEnrichment === "object"
      ? previewEnrichment
      : null
  );
  const [articleInfo, setArticleInfo] = useState(
    normalizeArticleInfo(previewArticleInfo)
  );
  const [articleDoiLookup, setArticleDoiLookup] = useState({
    loading: false,
    message: "",
    tone: "idle",
  });
  const [extractionExportData, setExtractionExportData] = useState(null);
  const [referenceDebugDownload, setReferenceDebugDownload] = useState(null);
  const [readerV2Data, setReaderV2Data] = useState(null);
  const [showReaderV2, setShowReaderV2] = useState(false);
  const [readerV2Opacity, setReaderV2Opacity] = useState(1);
  const [readerV2Layer, setReaderV2Layer] = useState("");
  const [hoveredItemId, setHoveredItemId] = useState(null);
  const [selectedItemId, setSelectedItemId] = useState(null);
  const [refDebugSteps, setRefDebugSteps] = useState([]);
  const [activeRefDebugKeys, setActiveRefDebugKeys] = useState(new Set());
  const [showRefDebug, setShowRefDebug] = useState(false);
  const [refDebugOpacity, setRefDebugOpacity] = useState(0.75);
  const [activeFile, setActiveFile] = useState(previewFile || null);
  const [dropActive, setDropActive] = useState(false);

  const viewerRef = useRef(null);
  const viewerShellRef = useRef(null);
  const snippetPopoverRef = useRef(null);
  const referenceElements = useRef(new Map());
  const citationHitMapRef = useRef(new Map());
  const activeCitationRef = useRef(null);
  const inlineCitationsKeyRef = useRef("");
  const fileInputRef = useRef(null);
  const readerV2ItemRefs = useRef(new Map());
  const extractProgressTimerRef = useRef(null);
  const articleDoiRequestIdRef = useRef(0);

  useEffect(() => {
    if (!extractStatus.loading) {
      if (extractProgressTimerRef.current) {
        window.clearInterval(extractProgressTimerRef.current);
        extractProgressTimerRef.current = null;
      }
      setExtractProgress({ value: 0, label: "" });
      return;
    }

    setExtractProgress({
      value: 6,
      label: getApproxExtractProgressLabel(6),
    });
    extractProgressTimerRef.current = window.setInterval(() => {
      setExtractProgress((current) => {
        const nextValue = Math.min(
          94,
          Math.max(6, Number(current.value || 0)) +
            getApproxExtractProgressStep(Number(current.value || 0))
        );
        return {
          value: nextValue,
          label: getApproxExtractProgressLabel(nextValue),
        };
      });
    }, 450);

    return () => {
      if (extractProgressTimerRef.current) {
        window.clearInterval(extractProgressTimerRef.current);
        extractProgressTimerRef.current = null;
      }
    };
  }, [extractStatus.loading]);

  useEffect(() => {
    if (!previewFile) {
      return;
    }
    const objectUrl = URL.createObjectURL(previewFile);
    setPreviewUrl(objectUrl);
    setActiveFile(previewFile);
    setReferencesVisualData({
      references: [],
      citations: [],
      contexts: [],
      citation_style: "",
      max_reference_index: null,
      bibliography_start_page: null,
    });
    setExtractEnrichment(null);
    setArticleInfo(normalizeArticleInfo(previewArticleInfo));
    setArticleDoiLookup({
      loading: false,
      message: "",
      tone: "idle",
    });
    setExtractionExportData(null);
    setReferenceDebugDownload(null);
    setSelectedReferenceId("");
    setHoveredReferenceId("");
    setSelectedCitationId("");
    setHoveredCitationId("");
    setReaderV2Data(null);
    setReaderV2Layer("");
    setHoveredItemId(null);
    setSelectedItemId(null);
    setShowReaderV2(false);
    setReaderV2Opacity(1);
    if (previewArticleInfo?.doi) {
      setArticleDoiInput(String(previewArticleInfo.doi));
    }
    return () => URL.revokeObjectURL(objectUrl);
  }, [previewFile, previewArticleInfo]);

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
    setExtractEnrichment(
      previewEnrichment && typeof previewEnrichment === "object"
        ? previewEnrichment
        : null
    );
  }, [previewEnrichment]);

  useEffect(() => {
    const nextArticleInfo = normalizeArticleInfo(previewArticleInfo);
    setArticleInfo(nextArticleInfo);
    if (nextArticleInfo?.doi) {
      setArticleDoiInput(nextArticleInfo.doi);
    }
  }, [previewArticleInfo]);

  useEffect(() => {
    const normalized = String(reportOriginalDoi || "").trim();
    if (!normalized) return;
    setArticleDoiInput((current) =>
      String(current || "").trim() ? current : normalized
    );
  }, [reportOriginalDoi]);

  useEffect(() => {
    setStats(previewStats || null);
  }, [previewStats]);

  useEffect(() => {
    const handler = (event) => {
      const file = event.detail?.file;
      if (!file) return;
      const objectUrl = URL.createObjectURL(file);
      setActiveFile(file);
      setReferencesVisualData({
        references: [],
        citations: [],
        contexts: [],
        citation_style: "",
        max_reference_index: null,
        bibliography_start_page: null,
      });
      setExtractEnrichment(null);
      setArticleInfo(null);
      setArticleDoiLookup({
        loading: false,
        message: "",
        tone: "idle",
      });
      setExtractionExportData(null);
      setReferenceDebugDownload(null);
      setSelectedReferenceId("");
      setHoveredReferenceId("");
      setSelectedCitationId("");
      setHoveredCitationId("");
      setReaderV2Data(null);
      setReaderV2Layer("");
      setHoveredItemId(null);
      setSelectedItemId(null);
      setShowReaderV2(false);
      setReaderV2Opacity(1);
      setArticleDoiInput("");
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
      const nextReferencesVisual =
        event.detail?.references_data &&
        typeof event.detail.references_data === "object"
          ? {
              references: Array.isArray(event.detail.references_data.references)
                ? event.detail.references_data.references
                : [],
              citations: Array.isArray(event.detail.references_data.citations)
                ? event.detail.references_data.citations
                : [],
              contexts: Array.isArray(event.detail.references_data.contexts)
                ? event.detail.references_data.contexts
                : [],
              citation_style: String(
                event.detail.references_data.citation_style || ""
              )
                .trim()
                .toLowerCase(),
              max_reference_index: Number.isFinite(
                Number(event.detail.references_data.max_reference_index)
              )
                ? Number(event.detail.references_data.max_reference_index)
                : null,
              bibliography_start_page: Number.isFinite(
                Number(event.detail.references_data.bibliography_start_page)
              )
                ? Number(event.detail.references_data.bibliography_start_page)
                : null,
            }
          : {
              references: [],
              citations: [],
              contexts: [],
              citation_style: "",
              max_reference_index: null,
              bibliography_start_page: null,
            };
      const nextStats = event.detail?.stats || null;
      const nextEnrichment =
        event.detail?.enrichment && typeof event.detail.enrichment === "object"
          ? event.detail.enrichment
          : null;
      const nextArticleInfo = normalizeArticleInfo(event.detail?.article_info);
      setSnippetsData(nextSnippets);
      setReferencesData(nextReferences);
      setReferencesVisualData(nextReferencesVisual);
      setStats(nextStats);
      setExtractEnrichment(nextEnrichment);
      setArticleInfo(nextArticleInfo);
      if (nextArticleInfo?.doi) {
        setArticleDoiInput(nextArticleInfo.doi);
      }
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
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP_${res.status}`);
        }
        const contentType = String(res.headers.get("content-type") || "");
        if (!contentType.includes("application/json")) {
          throw new Error("INVALID_RESPONSE_FORMAT");
        }
        return res.json();
      })
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setError("No se pudieron cargar los datos iniciales del reader.");
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
    if (!data || typeof data !== "object") return;
    const rawReferencesData =
      data.references_data && typeof data.references_data === "object"
        ? data.references_data
        : null;
    if (rawReferencesData) {
      setReferencesVisualData({
        references: Array.isArray(rawReferencesData.references)
          ? rawReferencesData.references
          : [],
        citations: Array.isArray(rawReferencesData.citations)
          ? rawReferencesData.citations
          : [],
        contexts: Array.isArray(rawReferencesData.contexts)
          ? rawReferencesData.contexts
          : [],
        citation_style: String(rawReferencesData.citation_style || "")
          .trim()
          .toLowerCase(),
        max_reference_index: Number.isFinite(
          Number(rawReferencesData.max_reference_index)
        )
          ? Number(rawReferencesData.max_reference_index)
          : null,
        bibliography_start_page: Number.isFinite(
          Number(rawReferencesData.bibliography_start_page)
        )
          ? Number(rawReferencesData.bibliography_start_page)
          : null,
      });
    }
    setExtractEnrichment(
      data.enrichment && typeof data.enrichment === "object"
        ? data.enrichment
        : null
    );
    const nextArticleInfo = normalizeArticleInfo(data.article_info);
    setArticleInfo(nextArticleInfo);
    if (nextArticleInfo?.doi) {
      setArticleDoiInput(nextArticleInfo.doi);
    }
  }, [data]);

  useEffect(() => {
    setSelectedSnippet(null);
    setSelectedSnippetAnchor(null);
    setSelectedSnippetPopoverStyle(null);
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
    const visualMeta = referencesVisualData || {};
    const doisTotal = normalizedReferences.filter((ref) => ref.doi).length;
    const rawCitationStyle =
      base.citation_style || data?.citation_style || visualMeta.citation_style || "";
    const rawMaxReferenceIndex =
      base.max_reference_index ??
      data?.max_reference_index ??
      visualMeta.max_reference_index;
    const rawBibliographyStartPage =
      base.bibliography_start_page ??
      data?.bibliography_start_page ??
      visualMeta.bibliography_start_page;
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
      citation_style: String(rawCitationStyle || "").trim().toLowerCase(),
      max_reference_index: Number.isFinite(Number(rawMaxReferenceIndex))
        ? Number(rawMaxReferenceIndex)
        : 0,
      bibliography_start_page: Number.isFinite(Number(rawBibliographyStartPage))
        ? Number(rawBibliographyStartPage)
        : null,
    };
  }, [stats, data, normalizedSnippets, normalizedReferences, referencesVisualData]);

  const referencesNumbered =
    effectiveStats.references_numbered ||
    normalizedReferences.some((ref) => ref.numbered);
  const citationStyle = String(
    effectiveStats.citation_style || (referencesNumbered ? "numeric" : "non_numeric")
  )
    .trim()
    .toLowerCase();
  const maxReferenceIndex = useMemo(() => {
    const explicit = Number(effectiveStats.max_reference_index);
    if (Number.isFinite(explicit) && explicit > 0) {
      return explicit;
    }
    const indexedMax = normalizedReferences.reduce((max, ref) => {
      const next = Number(ref?.index);
      if (Number.isFinite(next) && next > max) {
        return next;
      }
      return max;
    }, 0);
    if (indexedMax > 0) {
      return indexedMax;
    }
    const fallbackCount = Number(effectiveStats.references_total);
    return Number.isFinite(fallbackCount) && fallbackCount > 0 ? fallbackCount : 0;
  }, [
    effectiveStats.max_reference_index,
    effectiveStats.references_total,
    normalizedReferences,
  ]);
  const bibliographyStartPage = useMemo(() => {
    const value = Number(effectiveStats.bibliography_start_page);
    return Number.isFinite(value) && value > 0 ? value : null;
  }, [effectiveStats.bibliography_start_page]);
  const normalizedArticleDoiInput = useMemo(
    () => normalizeDoi(articleDoiInput),
    [articleDoiInput]
  );
  const effectiveArticleInfo = useMemo(() => {
    const normalized = normalizeArticleInfo(articleInfo);
    if (normalized) {
      return normalized;
    }
    if (!normalizedArticleDoiInput) {
      return null;
    }
    return {
      doi: normalizedArticleDoiInput,
      title: "",
      authors: [],
      year: null,
      venue: "",
      source: "",
      sources_used: [],
      references_count: 0,
      cited_by_count: 0,
      resolved: false,
      url: `https://doi.org/${normalizedArticleDoiInput}`,
    };
  }, [articleInfo, normalizedArticleDoiInput]);
  const hasArticleInfoTab = Boolean(effectiveArticleInfo?.doi);

  useEffect(() => {
    if (activeTab === "info" && !hasArticleInfoTab) {
      setActiveTab("extract");
    }
  }, [activeTab, hasArticleInfoTab]);

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
  const canExtract = !extractStatus.loading && Boolean(activeFile || resolvedPdfUrl);
  const canDownloadExtraction = Boolean(extractionExportData);
  const canDownloadDebug = Boolean(referenceDebugDownload?.url);
  const readerV2LayerOptions = useMemo(
    () => getReaderV2LayerKeys(readerV2Data),
    [readerV2Data]
  );
  const activeReaderV2Layer = useMemo(() => {
    if (!readerV2LayerOptions.length) return "";
    if (readerV2LayerOptions.includes(readerV2Layer)) return readerV2Layer;
    if (readerV2LayerOptions.includes("tokens")) return "tokens";
    return readerV2LayerOptions[0];
  }, [readerV2LayerOptions, readerV2Layer]);
  const readerV2RawLayerItems = useMemo(() => {
    if (!activeReaderV2Layer) return [];
    if (
      readerV2Data?.layers &&
      typeof readerV2Data.layers === "object" &&
      Array.isArray(readerV2Data.layers[activeReaderV2Layer])
    ) {
      return normalizeLayerItems(readerV2Data.layers[activeReaderV2Layer]);
    }
    if (activeReaderV2Layer === "tokens" && Array.isArray(readerV2Data?.items)) {
      return normalizeLayerItems(readerV2Data.items);
    }
    return [];
  }, [readerV2Data, activeReaderV2Layer]);
  const currentLayerOverlayItems = useMemo(() => {
    const withSourceIndex = readerV2RawLayerItems.map((item, index) => ({
      ...item,
      __sourceIndex: index,
    }));
    const orderedItems = sortItemsByReadingOrder(withSourceIndex, activeReaderV2Layer);
    return orderedItems.map((item, visualIndex) => ({
      ...item,
      __v2id: (() => {
        const sourceIndex = Number.isFinite(Number(item?.__sourceIndex))
          ? Number(item.__sourceIndex)
          : visualIndex;
        return getReaderV2ItemId(item, sourceIndex, activeReaderV2Layer || "layer");
      })(),
      __v2sourceId: (() => {
        const sourceIndex = Number.isFinite(Number(item?.__sourceIndex))
          ? Number(item.__sourceIndex)
          : visualIndex;
        return getReaderV2SourceId(item, sourceIndex, activeReaderV2Layer || "layer");
      })(),
    }));
  }, [readerV2RawLayerItems, activeReaderV2Layer]);
  const currentLayerItems = useMemo(() => {
    if (activeReaderV2Layer !== "tokens") {
      return currentLayerOverlayItems;
    }

    const groupedItems = [];
    const groupedIndexById = new Map();

    currentLayerOverlayItems.forEach((item, index) => {
      const sourceId = String(item?.__v2sourceId || item?.__v2id || `token-${index}`);
      const existingIndex = groupedIndexById.get(sourceId);
      if (existingIndex === undefined) {
        groupedIndexById.set(sourceId, groupedItems.length);
        groupedItems.push({
          ...item,
          __v2id: sourceId,
          __v2sourceId: sourceId,
          __fragmentCount: 1,
          __firstVisualIndex: index,
        });
        return;
      }

      const existing = groupedItems[existingIndex];
      existing.__fragmentCount = Number(existing.__fragmentCount || 1) + 1;

      const existingPage = Number(existing?.page);
      const nextPage = Number(item?.page);
      if (
        Number.isFinite(nextPage) &&
        (!Number.isFinite(existingPage) || nextPage < existingPage)
      ) {
        existing.page = nextPage;
      }
    });

    return groupedItems;
  }, [currentLayerOverlayItems, activeReaderV2Layer]);
  const readerV2PagesTotal = Array.isArray(readerV2Data?.pages)
    ? readerV2Data.pages.length
    : 0;
  const readerV2ItemsTotal = currentLayerItems.length;
  const readerV2AllItemsTotal = useMemo(
    () => countLayerItems(readerV2Data?.layers),
    [readerV2Data]
  );

  const handleReaderV2ItemHover = useCallback((itemId) => {
    setHoveredItemId(itemId || null);
  }, []);
  const handleReaderV2ItemSelect = useCallback((itemId) => {
    setSelectedItemId(itemId || null);
  }, []);
  const registerReaderV2ItemRow = useCallback((itemId) => {
    return (element) => {
      if (!itemId) return;
      if (element) {
        readerV2ItemRefs.current.set(itemId, element);
      } else {
        readerV2ItemRefs.current.delete(itemId);
      }
    };
  }, []);

  useEffect(() => {
    if (!readerV2LayerOptions.length) {
      if (readerV2Layer !== "") {
        setReaderV2Layer("");
      }
      return;
    }
    if (!readerV2LayerOptions.includes(readerV2Layer)) {
      setReaderV2Layer(
        readerV2LayerOptions.includes("tokens")
          ? "tokens"
          : readerV2LayerOptions[0]
      );
    }
  }, [readerV2LayerOptions, readerV2Layer]);

  useEffect(() => {
    setHoveredItemId(null);
    setSelectedItemId(null);
  }, [activeReaderV2Layer]);

  useEffect(() => {
    if (!hoveredItemId) return;
    const exists = currentLayerItems.some(
      (item) => (item.__v2sourceId || item.__v2id) === hoveredItemId
    );
    if (!exists) {
      setHoveredItemId(null);
    }
  }, [hoveredItemId, currentLayerItems]);

  useEffect(() => {
    if (!selectedItemId) return;
    const exists = currentLayerItems.some(
      (item) => (item.__v2sourceId || item.__v2id) === selectedItemId
    );
    if (!exists) {
      setSelectedItemId(null);
      return;
    }
    const rowEl = readerV2ItemRefs.current.get(selectedItemId);
    if (rowEl && typeof rowEl.scrollIntoView === "function") {
      rowEl.scrollIntoView({ block: "nearest" });
    }
  }, [selectedItemId, currentLayerItems]);

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

  useEffect(() => {
    if (!selectedSnippet || selectedSnippet.highlightMode !== "paragraph") {
      return;
    }
    const refIndex = Number(selectedSnippet.reference_index);
    if (!Number.isFinite(refIndex)) {
      return;
    }
    const inlineSnippet = inlineSnippetByIndex.get(refIndex);
    if (!inlineSnippet || !Number.isFinite(Number(inlineSnippet.page))) {
      return;
    }
    if (Number(selectedSnippet.page) === Number(inlineSnippet.page)) {
      if (
        normalizeForMatch(selectedSnippet.highlight_snippet || "") ===
        normalizeForMatch(inlineSnippet.snippet || "")
      ) {
        return;
      }
    }
    setSelectedSnippet((current) => {
      if (!current) return current;
      return {
        ...current,
        page: inlineSnippet.page,
        highlight_snippet: inlineSnippet.snippet,
      };
    });
  }, [inlineSnippetByIndex, selectedSnippet]);

  const referencesWithStats = useMemo(() => {
    return filteredReferences.map((ref) => {
      const statsEntry = citationStatsByReference.get(ref.index);
      const pages = statsEntry
        ? Array.from(statsEntry.pages).sort((a, b) => a - b)
        : [];
      const extractorSnippet = referenceSnippetByIndex.get(ref.index) || null;
      const inlineSnippet = inlineSnippetByIndex.get(ref.index) || null;
      const linkedSnippet = extractorSnippet || inlineSnippet;
      const summary = extractReferenceSummary(ref.raw);
      const snippetPage = Number(inlineSnippet?.page ?? extractorSnippet?.page ?? "");
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

  const visualReferenceEntries = useMemo(
    () =>
      Array.isArray(referencesVisualData?.references)
        ? referencesVisualData.references
        : [],
    [referencesVisualData]
  );
  const visualCitationMentions = useMemo(
    () =>
      Array.isArray(referencesVisualData?.citations)
        ? referencesVisualData.citations
        : [],
    [referencesVisualData]
  );
  const visualCitationContexts = useMemo(
    () =>
      Array.isArray(referencesVisualData?.contexts)
        ? referencesVisualData.contexts
        : [],
    [referencesVisualData]
  );
  const visualReferenceTotal = visualReferenceEntries.length;
  const visualCitationTotal = visualCitationMentions.length;
  const visualContextTotal = visualCitationContexts.length;

  const parseRefIndex = (refId) => {
    const match = String(refId || "").match(/^ref-(\d+)$/);
    if (!match) return null;
    const value = Number(match[1]);
    return Number.isFinite(value) && value > 0 ? value : null;
  };

  const mentionCountByRefId = useMemo(() => {
    const map = new Map();
    visualCitationMentions.forEach((item) => {
      const refId = String(item?.ref_id || "");
      if (!refId) return;
      map.set(refId, (map.get(refId) || 0) + 1);
    });
    return map;
  }, [visualCitationMentions]);

  const referencesByRefId = useMemo(() => {
    const map = new Map();
    visualReferenceEntries.forEach((entry, index) => {
      const refId = String(entry?.ref_id || "");
      if (!refId) return;
      const indexFromRefId = parseRefIndex(refId);
      const baseRef =
        indexFromRefId && referenceByIndex.has(indexFromRefId)
          ? referenceByIndex.get(indexFromRefId)
          : null;
      const referenceText = String(entry?.text || baseRef?.raw || "").trim();
      const summary = extractReferenceSummary(referenceText);
      const pageValue = Number(entry?.page);
      map.set(refId, {
        ref_id: refId,
        index: indexFromRefId || Number(entry?.index) || index + 1,
        text: referenceText,
        title: summary.title,
        author: summary.author,
        doi: entry?.doi || baseRef?.doi || null,
        page: Number.isFinite(pageValue) ? pageValue : null,
        box: normalizeOverlayBox(entry?.box),
        structure_source: String(entry?.structure_source || "").trim(),
      });
    });
    if (!map.size) {
      referencesWithStats.forEach((ref, index) => {
        const refId = `ref-${Number(ref?.index) || index + 1}`;
        map.set(refId, {
          ref_id: refId,
          index: Number(ref?.index) || index + 1,
          text: String(ref?.raw || ""),
          title: ref?.display_title || "",
          author: ref?.display_author || "",
          doi: ref?.doi || null,
          page:
            Number.isFinite(Number(ref?.display_page)) && Number(ref.display_page) > 0
              ? Number(ref.display_page) - 1
              : null,
          box: null,
        });
      });
    }
    return map;
  }, [visualReferenceEntries, referenceByIndex, referencesWithStats]);

  const referenceRows = useMemo(() => {
    const rows = Array.from(referencesByRefId.values()).map((row) => ({
      ...row,
      mentions_total: mentionCountByRefId.get(row.ref_id) || 0,
    }));
    rows.sort((a, b) => (a.index || 0) - (b.index || 0));
    return rows;
  }, [referencesByRefId, mentionCountByRefId]);

  const filteredReferenceRows = useMemo(() => {
    const query = referenceQuery.trim().toLowerCase();
    if (!query) return referenceRows;
    return referenceRows.filter((row) => {
      return (
        row.text.toLowerCase().includes(query) ||
        (row.doi && row.doi.toLowerCase().includes(query)) ||
        (row.title && row.title.toLowerCase().includes(query))
      );
    });
  }, [referenceRows, referenceQuery]);

  const citationMentionsByRefId = useMemo(() => {
    const map = new Map();
    visualCitationMentions.forEach((item) => {
      const refId = String(item?.ref_id || "");
      if (!refId) return;
      const list = map.get(refId) || [];
      list.push(item);
      map.set(refId, list);
    });
    return map;
  }, [visualCitationMentions]);
  const selectedReferenceMentions = useMemo(() => {
    if (!selectedReferenceId) return [];
    const mentions = citationMentionsByRefId.get(selectedReferenceId) || [];
    return [...mentions].sort((mentionA, mentionB) => {
      const pageA = Number(mentionA?.page);
      const pageB = Number(mentionB?.page);
      if (Number.isFinite(pageA) && Number.isFinite(pageB) && pageA !== pageB) {
        return pageA - pageB;
      }
      const boxA = normalizeOverlayBox(mentionA?.box);
      const boxB = normalizeOverlayBox(mentionB?.box);
      const yA = boxA ? Number(boxA[1]) : Number.MAX_SAFE_INTEGER;
      const yB = boxB ? Number(boxB[1]) : Number.MAX_SAFE_INTEGER;
      if (yA !== yB) {
        return yA - yB;
      }
      const xA = boxA ? Number(boxA[0]) : Number.MAX_SAFE_INTEGER;
      const xB = boxB ? Number(boxB[0]) : Number.MAX_SAFE_INTEGER;
      return xA - xB;
    });
  }, [selectedReferenceId, citationMentionsByRefId]);

  const citationContextsByRefId = useMemo(() => {
    const map = new Map();
    visualCitationContexts.forEach((item) => {
      const refId = String(item?.ref_id || "");
      if (!refId) return;
      const list = map.get(refId) || [];
      list.push(item);
      map.set(refId, list);
    });
    return map;
  }, [visualCitationContexts]);

  const referencesOverlayItems = useMemo(() => {
    if (activeTab !== "references") return [];
    const items = [];
    visualReferenceEntries.forEach((entry) =>
      items.push({ ...entry, item_type: "reference-entry" })
    );
    visualCitationMentions.forEach((mention) =>
      items.push({ ...mention, item_type: "citation-mention" })
    );
    visualCitationContexts.forEach((context) =>
      items.push({ ...context, item_type: "citation-context" })
    );
    return items;
  }, [
    activeTab,
    visualReferenceEntries,
    visualCitationMentions,
    visualCitationContexts,
  ]);
  const referencesPanelNotice = useMemo(() => {
    if (!referenceRows.length) {
      if (extractStatus.loading) {
        return {
          tone: "info",
          text: "Extraccion en curso. Las referencias apareceran al finalizar.",
        };
      }
      if (extractStatus.error) {
        return {
          tone: "error",
          text: "No se han podido cargar referencias para este PDF.",
        };
      }
      return {
        tone: "warning",
        text: "No se detectaron referencias. Prueba con otro PDF o revisa la calidad del texto extraible.",
      };
    }
    if (!visualCitationTotal) {
      return {
        tone: "warning",
        text: "Se detectaron referencias, pero no citas enlazables en el cuerpo del documento.",
      };
    }
    return {
      tone: "success",
      text: `${visualCitationTotal} citas enlazables y ${visualContextTotal} contextos listos para navegacion.`,
    };
  }, [
    referenceRows.length,
    extractStatus.loading,
    extractStatus.error,
    visualCitationTotal,
    visualContextTotal,
  ]);
  const layersPanelNotice = useMemo(() => {
    if (!readerV2Data) {
      return {
        tone: "info",
        text: 'Ejecuta "Extraer" para preparar capas visuales.',
      };
    }
    if (!readerV2LayerOptions.length || !readerV2AllItemsTotal) {
      return {
        tone: "warning",
        text: "Extraccion completada sin capas visuales utilizables para este PDF.",
      };
    }
    if (!currentLayerItems.length) {
      const layerLabel = activeReaderV2Layer
        ? (READER_V2_LAYER_LABELS[activeReaderV2Layer] || activeReaderV2Layer)
        : "seleccionada";
      return {
        tone: "warning",
        text: `La capa ${layerLabel} esta vacia. Cambia a otra capa si esta disponible.`,
      };
    }
    return {
      tone: "success",
      text: `${currentLayerItems.length} elementos en la capa activa. ${readerV2AllItemsTotal} elementos totales en capas.`,
    };
  }, [
    readerV2Data,
    readerV2LayerOptions,
    readerV2AllItemsTotal,
    currentLayerItems.length,
    activeReaderV2Layer,
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

  const updateSelectedSnippetPopoverPosition = () => {
    const shellEl = viewerShellRef.current;
    const viewerEl = viewerRef.current;
    if (!shellEl || !viewerEl || !selectedSnippet) {
      setSelectedSnippetPopoverStyle(null);
      return;
    }

    const shellRect = shellEl.getBoundingClientRect();
    const toolbarEl = shellEl.querySelector(".reader-toolbar");
    const toolbarBottom = toolbarEl
      ? toolbarEl.getBoundingClientRect().bottom - shellRect.top
      : 0;

    const popEl = snippetPopoverRef.current;
    const popWidth = Math.max(260, popEl?.offsetWidth || 300);
    const popHeight = Math.max(140, popEl?.offsetHeight || 220);
    const minTop = Math.max(12, toolbarBottom + 6);
    const maxTop = Math.max(minTop, shellEl.clientHeight - popHeight - 12);
    const minLeft = 12;
    const maxLeft = Math.max(minLeft, shellEl.clientWidth - popWidth - 12);

    let top = minTop;
    let left = maxLeft;
    let anchorPageRect = null;
    let anchorRect = null;

    if (selectedSnippetAnchor?.anchorRect && Number.isFinite(selectedSnippetAnchor.page)) {
      const pageEl = viewerEl.querySelector(
        `.pdf-reader__page[data-page-number="${selectedSnippetAnchor.page}"]`
      );
      if (pageEl) {
        anchorPageRect = pageEl.getBoundingClientRect();
        anchorRect = {
          left: Number(selectedSnippetAnchor.anchorRect.left),
          top: Number(selectedSnippetAnchor.anchorRect.top),
          width: Math.max(2, Number(selectedSnippetAnchor.anchorRect.width || 0)),
          height: Math.max(2, Number(selectedSnippetAnchor.anchorRect.height || 0)),
        };
      }
    }

    if (!anchorRect && Number.isFinite(Number(selectedSnippet.page))) {
      const pageEl = viewerEl.querySelector(
        `.pdf-reader__page[data-page-number="${Number(selectedSnippet.page)}"]`
      );
      if (pageEl) {
        const pageRect = pageEl.getBoundingClientRect();
        anchorPageRect = pageRect;
        const refIndex = Number(selectedSnippet.reference_index);
        if (Number.isFinite(refIndex)) {
          const citationHits = Array.from(pageEl.querySelectorAll(".citation-hit"));
          const matchHit = citationHits.find((hit) => {
            const refs = (hit.dataset.citationRefs || "")
              .split(",")
              .map((value) => Number(value.trim()))
              .filter((value) => Number.isFinite(value));
            return refs.includes(refIndex);
          });
          if (matchHit) {
            const rect = matchHit.getBoundingClientRect();
            anchorRect = {
              left: Math.max(0, rect.left - pageRect.left),
              top: Math.max(0, rect.top - pageRect.top),
              width: Math.max(2, rect.width),
              height: Math.max(2, rect.height),
            };
          }
        }

        if (!anchorRect) {
          const paragraphHit = pageEl.querySelector(".reader-paragraph-hit");
          if (paragraphHit) {
            const rect = paragraphHit.getBoundingClientRect();
            anchorRect = {
              left: Math.max(0, rect.left - pageRect.left),
              top: Math.max(0, rect.top - pageRect.top),
              width: Math.max(2, rect.width),
              height: Math.max(2, rect.height),
            };
          }
        }
      }
    }

    if (anchorRect && anchorPageRect) {
      const anchorLeft = anchorPageRect.left - shellRect.left + anchorRect.left;
      const anchorTop = anchorPageRect.top - shellRect.top + anchorRect.top;
      const anchorWidth = Math.max(2, anchorRect.width || 0);
      const anchorHeight = Math.max(2, anchorRect.height || 0);
      const rightCandidate = anchorLeft + anchorWidth + 8;
      const leftCandidate = anchorLeft - popWidth - 8;
      const nearPageRight = anchorPageRect.right - shellRect.left + 8;

      if (rightCandidate + popWidth <= shellEl.clientWidth - minLeft) {
        left = rightCandidate;
      } else if (leftCandidate >= minLeft) {
        left = leftCandidate;
      } else {
        left = Math.min(Math.max(minLeft, nearPageRight), maxLeft);
      }
      top = anchorTop + anchorHeight / 2 - popHeight / 2;
    } else if (Number.isFinite(Number(selectedSnippet.page))) {
      const pageEl = viewerEl.querySelector(
        `.pdf-reader__page[data-page-number="${Number(selectedSnippet.page)}"]`
      );
      if (pageEl) {
        const pageRect = pageEl.getBoundingClientRect();
        left = Math.min(Math.max(minLeft, pageRect.right - shellRect.left + 8), maxLeft);
        top = pageRect.top - shellRect.top + 24;
      }
    }

    setSelectedSnippetPopoverStyle({
      top: Math.min(Math.max(minTop, top), maxTop),
      left: Math.min(Math.max(minLeft, left), maxLeft),
    });
  };

  useEffect(() => {
    if (!viewerRef.current) return;
    updateCitationPopoverPosition();
  }, [activeCitation]);

  useEffect(() => {
    if (!selectedSnippet) {
      setSelectedSnippetPopoverStyle(null);
      return;
    }
    const timer = window.setTimeout(updateSelectedSnippetPopoverPosition, 0);
    return () => window.clearTimeout(timer);
  }, [selectedSnippet, selectedSnippetAnchor]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl) return;
    const onScroll = () => updateCitationPopoverPosition();
    viewerEl.addEventListener("scroll", onScroll);
    return () => viewerEl.removeEventListener("scroll", onScroll);
  }, [activeCitation]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl || !selectedSnippet) return;
    const onMove = () => updateSelectedSnippetPopoverPosition();
    viewerEl.addEventListener("scroll", onMove);
    window.addEventListener("resize", onMove);
    return () => {
      viewerEl.removeEventListener("scroll", onMove);
      window.removeEventListener("resize", onMove);
    };
  }, [selectedSnippet, selectedSnippetAnchor]);

  useEffect(() => {
    setActiveCitation(null);
  }, [resolvedPdfUrl]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl) return;
    if (visualCitationMentions.length > 0) {
      viewerEl
        .querySelectorAll(".reader-citation-layer")
        .forEach((layer) => layer.remove());
      setInlineCitations([]);
      setActiveCitation(null);
      return;
    }
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
          const hits = collectCitationHitsForPage(pageEl, {
            citationStyle,
            maxReferenceIndex,
            bibliographyStartPage,
          });
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
              hitEl.dataset.citationKind = hit.kind || "numeric";
              hitEl.dataset.citationRefs = (hit.numbers || []).join(",");
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
        const nextKey = hitsList
          .map((hit) => `${hit.id}:${(hit.numbers || []).join(",")}`)
          .join("|");
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
  }, [
    resolvedPdfUrl,
    visualCitationMentions.length,
    citationStyle,
    maxReferenceIndex,
    bibliographyStartPage,
  ]);

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
    setSelectedSnippetAnchor(null);
    setSelectedSnippet(snippet);
    setHighlightNotice("");
    const pageNumber = Number(snippet?.page);
    if (Number.isFinite(pageNumber)) {
      scrollToPdfPageIndex(pageNumber - 1);
    }
  };

  const handleHighlight = (result) => {
    if (!selectedSnippet) return;
    const matched =
      typeof result === "object" && result !== null
        ? Boolean(result.matched)
        : Boolean(result);
    const anchorRect =
      typeof result === "object" && result !== null ? result.anchorRect : null;
    const page =
      typeof result === "object" && result !== null ? Number(result.page) : null;

    if (matched) {
      setHighlightNotice("");
    } else {
      setHighlightNotice("No se encontro el texto exacto; resaltado aproximado.");
    }
    if (
      anchorRect &&
      Number.isFinite(page) &&
      Number.isFinite(Number(anchorRect.left)) &&
      Number.isFinite(Number(anchorRect.top))
    ) {
      setSelectedSnippetAnchor({
        page,
        anchorRect: {
          left: Number(anchorRect.left),
          top: Number(anchorRect.top),
          width: Math.max(2, Number(anchorRect.width || 0)),
          height: Math.max(2, Number(anchorRect.height || 0)),
        },
      });
    } else if (!matched) {
      setSelectedSnippetAnchor(null);
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

  const scrollReferenceRowToTop = useCallback((refId) => {
    if (!refId) return false;
    const el = referenceElements.current.get(refId);
    if (!el) return false;
    const scrollContainer = el.closest(".reader-panel");
    const topPadding = 14;
    if (scrollContainer && scrollContainer.scrollHeight > scrollContainer.clientHeight) {
      const containerRect = scrollContainer.getBoundingClientRect();
      const elementRect = el.getBoundingClientRect();
      const nextTop =
        scrollContainer.scrollTop +
        (elementRect.top - containerRect.top) -
        topPadding;
      scrollContainer.scrollTo({
        top: Math.max(0, Math.round(nextTop)),
        behavior: "smooth",
      });
      return true;
    }
    if (el.scrollIntoView) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      return true;
    }
    return false;
  }, []);

  const jumpToReference = (refKey) => {
    if (!refKey) return;
    let resolvedRefId = String(refKey || "");
    if (resolvedRefId.startsWith("idx:")) {
      const indexValue = Number(resolvedRefId.slice(4));
      if (Number.isFinite(indexValue) && indexValue > 0) {
        resolvedRefId = `ref-${indexValue}`;
      }
    } else if (resolvedRefId.startsWith("doi:")) {
      const doiValue = normalizeDoi(resolvedRefId.slice(4));
      const matchedRow = referenceRows.find(
        (row) => normalizeDoi(row.doi || "") === doiValue
      );
      if (matchedRow?.ref_id) {
        resolvedRefId = matchedRow.ref_id;
      }
    }
    setActiveTab("references");
    setSelectedReferenceId(resolvedRefId);
    setActiveReferenceKey(resolvedRefId);
    setTimeout(() => {
      scrollReferenceRowToTop(resolvedRefId);
    }, 150);
  };

  const scrollReferenceTargetToTop = useCallback((target, fallbackPage = null) => {
    const viewerEl = viewerRef.current;
    const fallbackIndex = Number(fallbackPage);
    const rawPage = Number(target?.page);
    const pageIndex = Number.isFinite(rawPage)
      ? rawPage
      : (Number.isFinite(fallbackIndex) ? fallbackIndex : null);
    if (!Number.isFinite(pageIndex) || pageIndex < 0) {
      return false;
    }
    if (!viewerEl) {
      scrollToPdfPageIndex(pageIndex);
      return true;
    }
    const pageEl = viewerEl.querySelector(
      `.pdf-reader__page[data-page-number="${pageIndex + 1}"]`
    );
    if (!pageEl) {
      scrollToPdfPageIndex(pageIndex);
      return true;
    }

    const pageRect = pageEl.getBoundingClientRect();
    const viewerRect = viewerEl.getBoundingClientRect();
    const normalizedBox = normalizeOverlayBox(target?.box);
    const boxTopOffset = normalizedBox ? normalizedBox[1] * pageEl.clientHeight : 0;
    const topPadding = 28;
    const nextTop =
      viewerEl.scrollTop +
      (pageRect.top - viewerRect.top) +
      boxTopOffset -
      topPadding;
    viewerEl.scrollTo({
      top: Math.max(0, Math.round(nextTop)),
      behavior: "smooth",
    });
    return true;
  }, [viewerRef]);

  const resolveReferenceBlockAnchor = useCallback((target, refId) => {
    if (!target) return target;
    const contexts = citationContextsByRefId.get(refId) || [];
    if (!contexts.length) return target;

    const targetPage = Number(target?.page);
    const targetBox = normalizeOverlayBox(target?.box);
    const samePageContexts = Number.isFinite(targetPage)
      ? contexts.filter((ctx) => Number(ctx?.page) === targetPage)
      : contexts;

    const candidateContexts = samePageContexts.length ? samePageContexts : contexts;
    if (!candidateContexts.length) return target;

    if (targetBox) {
      const targetTop = Number(targetBox[1]);
      const targetBottom = targetTop + Number(targetBox[3]);
      const overlapCandidate = candidateContexts.find((ctx) => {
        const ctxBox = normalizeOverlayBox(ctx?.box);
        if (!ctxBox) return false;
        const ctxTop = Number(ctxBox[1]);
        const ctxBottom = ctxTop + Number(ctxBox[3]);
        return !(ctxBottom < targetTop || ctxTop > targetBottom);
      });
      if (overlapCandidate) {
        return overlapCandidate;
      }
    }

    const ordered = [...candidateContexts].sort((a, b) => {
      const pageA = Number(a?.page);
      const pageB = Number(b?.page);
      if (Number.isFinite(pageA) && Number.isFinite(pageB) && pageA !== pageB) {
        return pageA - pageB;
      }
      const boxA = normalizeOverlayBox(a?.box);
      const boxB = normalizeOverlayBox(b?.box);
      const topA = boxA ? Number(boxA[1]) : Number.MAX_SAFE_INTEGER;
      const topB = boxB ? Number(boxB[1]) : Number.MAX_SAFE_INTEGER;
      return topA - topB;
    });
    return ordered[0] || target;
  }, [citationContextsByRefId]);

  const copyToClipboard = (value) => {
    if (!value) return;
    navigator.clipboard?.writeText(value).catch(() => {});
  };

  const selectedReference = useMemo(() => {
    const refIndex = Number(selectedSnippet?.reference_index);
    if (!Number.isFinite(refIndex)) return null;
    return referenceByIndex.get(refIndex) || null;
  }, [selectedSnippet, referenceByIndex]);

  const handleCreateReport = () => {
    const modalEl = document.getElementById("reportModal");
    const bootstrapApi = window.bootstrap;
    if (!modalEl || !bootstrapApi?.Modal) {
      return;
    }

    if (typeof window.prefillReportModal === "function") {
      window.prefillReportModal({
        originalDoi: selectedReference?.doi || reportOriginalDoi || "",
        incorrectDoi: reportIncorrectDoi || "",
        originalMetadata: "",
        incorrectMetadata: "",
      });
    }

    const modal = bootstrapApi.Modal.getOrCreateInstance(modalEl);
    modal.show();
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
    const payloadCitationStyle = String(
      baseStats.citation_style || payload?.citation_style || ""
    )
      .trim()
      .toLowerCase();
    const payloadMaxReferenceIndex = Number(
      baseStats.max_reference_index ?? payload?.max_reference_index
    );
    const payloadBibliographyStartPage = Number(
      baseStats.bibliography_start_page ?? payload?.bibliography_start_page
    );
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
      citation_style: payloadCitationStyle,
      max_reference_index:
        Number.isFinite(payloadMaxReferenceIndex) && payloadMaxReferenceIndex > 0
          ? payloadMaxReferenceIndex
          : 0,
      bibliography_start_page:
        Number.isFinite(payloadBibliographyStartPage) && payloadBibliographyStartPage > 0
          ? payloadBibliographyStartPage
          : null,
    };
    const rawLayers =
      payload?.layers && typeof payload.layers === "object"
        ? payload.layers
        : (payload?.reader_data?.layers && typeof payload.reader_data.layers === "object"
          ? payload.reader_data.layers
          : null);
    const normalizedLayers = {};
    if (rawLayers) {
      Object.keys(rawLayers).forEach((layerKey) => {
        if (Array.isArray(rawLayers[layerKey])) {
          normalizedLayers[layerKey] = rawLayers[layerKey];
        }
      });
    }
    if (
      !Object.keys(normalizedLayers).length &&
      Array.isArray(payload?.items)
    ) {
      normalizedLayers.tokens = payload.items;
    }
    const pagesSource = Array.isArray(payload?.pages)
      ? payload.pages
      : (Array.isArray(payload?.reader_data?.pages) ? payload.reader_data.pages : []);
    const readerData = {
      pages: pagesSource,
      layers: normalizedLayers,
    };

    const toRefId = (rawItem, fallbackIndex) => {
      const explicit = String(
        rawItem?.ref_id || rawItem?.reference_id || rawItem?.refId || ""
      ).trim();
      if (explicit) return explicit;
      const indexValue = Number(rawItem?.index);
      if (Number.isFinite(indexValue) && indexValue > 0) {
        return `ref-${indexValue}`;
      }
      return `ref-${fallbackIndex + 1}`;
    };
    const normalizeReferenceItems = (source, itemType) => {
      if (!Array.isArray(source)) return [];
      return source.map((item, index) => {
        const resolvedPageCandidate =
          item?.resolved_page !== undefined && item?.resolved_page !== null
            ? item.resolved_page
            : item?.page;
        const resolvedBoxCandidate =
          Array.isArray(item?.resolved_box) && item.resolved_box.length >= 4
            ? item.resolved_box
            : item?.box;
        const page = normalizeOverlayPage(resolvedPageCandidate);
        const box = normalizeOverlayBox(resolvedBoxCandidate);
        const refId = toRefId(item, index);
        return {
          id: String(item?.id || `${itemType}-${index + 1}-${refId}`),
          ref_id: refId,
          index:
            Number.isFinite(Number(item?.index)) && Number(item.index) > 0
              ? Number(item.index)
              : null,
          text: String(item?.text || item?.raw || ""),
          page,
          box,
          structure_source: String(item?.structure_source || "").trim(),
          item_type: itemType,
        };
      });
    };
    const rawReferencesData =
      payload?.references_data && typeof payload.references_data === "object"
        ? payload.references_data
        : {};
    const referencesVisual = {
      references: normalizeReferenceItems(
        rawReferencesData.references,
        "reference-entry"
      ),
      citations: normalizeReferenceItems(
        rawReferencesData.citations,
        "citation-mention"
      ),
      contexts: normalizeReferenceItems(
        rawReferencesData.contexts,
        "citation-context"
      ),
      citation_style: String(rawReferencesData.citation_style || "")
        .trim()
        .toLowerCase(),
      max_reference_index: Number.isFinite(Number(rawReferencesData.max_reference_index))
        ? Number(rawReferencesData.max_reference_index)
        : null,
      bibliography_start_page: Number.isFinite(
        Number(rawReferencesData.bibliography_start_page)
      )
        ? Number(rawReferencesData.bibliography_start_page)
        : null,
    };
    if (!referencesVisual.references.length && Array.isArray(references)) {
      referencesVisual.references = references.map((ref, index) => {
        const refIndex =
          Number.isFinite(Number(ref?.index)) && Number(ref.index) > 0
            ? Number(ref.index)
            : index + 1;
        return {
          id: `reference-entry-ref-${refIndex}`,
          ref_id: `ref-${refIndex}`,
          index: refIndex,
          text: String(ref?.raw || ""),
          page: null,
          box: null,
          item_type: "reference-entry",
        };
      });
    }
    if (!stats.citation_style && referencesVisual.citation_style) {
      stats.citation_style = referencesVisual.citation_style;
    }
    if (
      (!Number.isFinite(Number(stats.max_reference_index)) ||
        Number(stats.max_reference_index) <= 0) &&
      Number.isFinite(Number(referencesVisual.max_reference_index))
    ) {
      stats.max_reference_index = Number(referencesVisual.max_reference_index);
    }
    if (
      !Number.isFinite(Number(stats.bibliography_start_page)) &&
      Number.isFinite(Number(referencesVisual.bibliography_start_page))
    ) {
      stats.bibliography_start_page = Number(referencesVisual.bibliography_start_page);
    }

    return { snippets, references, stats, readerData, referencesVisual };
  };

  const buildNestedReferencesForExport = (references, citations, contexts) => {
    const safeReferences = Array.isArray(references) ? references : [];
    const safeCitations = Array.isArray(citations) ? citations : [];
    const safeContexts = Array.isArray(contexts) ? contexts : [];
    const CONTEXT_ID_PREFIX = "citation-context-";

    const contextByCitationId = new Map();
    safeContexts.forEach((contextItem) => {
      const contextId = String(contextItem?.id || "").trim();
      if (!contextId.startsWith(CONTEXT_ID_PREFIX)) return;
      const citationId = contextId.slice(CONTEXT_ID_PREFIX.length).trim();
      if (!citationId) return;
      contextByCitationId.set(citationId, contextItem);
    });

    const citationsByRefId = new Map();
    safeCitations.forEach((citationItem) => {
      const refId = String(citationItem?.ref_id || "").trim();
      if (!refId) return;
      const citationId = String(citationItem?.id || "").trim();
      const linkedContext = citationId ? (contextByCitationId.get(citationId) || null) : null;
      const citationWithContext = {
        ...citationItem,
        context: linkedContext,
      };
      if (!citationsByRefId.has(refId)) {
        citationsByRefId.set(refId, []);
      }
      citationsByRefId.get(refId).push(citationWithContext);
    });

    const nestedReferences = safeReferences.map((referenceItem) => {
      const refId = String(referenceItem?.ref_id || "").trim();
      return {
        ...referenceItem,
        citations: refId ? (citationsByRefId.get(refId) || []) : [],
      };
    });

    const existingRefIds = new Set(
      nestedReferences
        .map((item) => String(item?.ref_id || "").trim())
        .filter(Boolean)
    );
    citationsByRefId.forEach((groupedCitations, refId) => {
      if (existingRefIds.has(refId)) return;
      nestedReferences.push({
        id: `reference-entry-${refId}`,
        ref_id: refId,
        index: null,
        text: "",
        page: null,
        box: null,
        doi: null,
        citations: groupedCitations,
      });
    });

    return nestedReferences;
  };

  const buildExtractionExportData = (payload, result, file) => {
    const rawReferencesData =
      payload?.references_data && typeof payload.references_data === "object"
        ? payload.references_data
        : {};
    const references = Array.isArray(rawReferencesData.references)
      ? rawReferencesData.references
      : result?.referencesVisual?.references || [];
    const citations = Array.isArray(rawReferencesData.citations)
      ? rawReferencesData.citations
      : result?.referencesVisual?.citations || [];
    const contexts = Array.isArray(rawReferencesData.contexts)
      ? rawReferencesData.contexts
      : result?.referencesVisual?.contexts || [];
    const nestedReferences = buildNestedReferencesForExport(
      references,
      citations,
      contexts
    );
    const resolvedCitationStyle = String(
      rawReferencesData.citation_style ||
        result?.stats?.citation_style ||
        payload?.citation_style ||
        ""
    )
      .trim()
      .toLowerCase();
    const maxReferenceIndexCandidate =
      rawReferencesData.max_reference_index ??
      result?.stats?.max_reference_index ??
      payload?.max_reference_index;
    const bibliographyStartPageCandidate =
      rawReferencesData.bibliography_start_page ??
      result?.stats?.bibliography_start_page ??
      payload?.bibliography_start_page;
    const maxReferenceIndex = Number(maxReferenceIndexCandidate);
    const bibliographyStartPage = Number(bibliographyStartPageCandidate);
    const statsForExport =
      result?.stats && typeof result.stats === "object"
        ? result.stats
        : (payload?.stats && typeof payload.stats === "object" ? payload.stats : {});
    const fileName = String(file?.name || payload?.file_name || payload?.filename || "document.pdf");
    const engine = String(
      statsForExport?.engine_used || payload?.engine_used || PREVIEW_EXTRACT_ENGINE
    ).trim();
    const exportArticleInfo = normalizeArticleInfo(payload?.article_info);
    const exportEnrichment =
      payload?.enrichment && typeof payload.enrichment === "object"
        ? payload.enrichment
        : null;
    return {
      file_name: fileName,
      engine: engine || PREVIEW_EXTRACT_ENGINE,
      citation_style: resolvedCitationStyle,
      max_reference_index: Number.isFinite(maxReferenceIndex) ? maxReferenceIndex : null,
      bibliography_start_page: Number.isFinite(bibliographyStartPage)
        ? bibliographyStartPage
        : null,
      stats: statsForExport,
      article_info: exportArticleInfo,
      enrichment: exportEnrichment,
      references: nestedReferences,
    };
  };

  const downloadExtractionJson = (exportData) => {
    if (!exportData || typeof exportData !== "object") return;
    const jsonData = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonData], { type: "application/json" });
    const downloadUrl = URL.createObjectURL(blob);
    const rawFileName = String(exportData.file_name || "document.pdf");
    const baseName = rawFileName.replace(/\.[^./\\]+$/, "").trim() || "document";
    const safeBaseName = baseName.replace(/[<>:"/\\|?*\u0000-\u001F]+/g, "_").replace(/\s+/g, "_");
    const downloadName = `${safeBaseName}_refs_citations_contexts.json`;
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = downloadName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(downloadUrl);
  };

  const downloadReferenceDebugJson = (downloadInfo) => {
    const downloadUrl = String(downloadInfo?.url || "").trim();
    if (!downloadUrl) return;
    const link = document.createElement("a");
    link.href = downloadUrl;
    if (downloadInfo?.filename) {
      link.download = downloadInfo.filename;
    }
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const describeExtractionOutcome = (result, nextLayer, nextItems) => {
    const referencesCount = Math.max(
      Number(result?.references?.length || 0),
      Number(result?.referencesVisual?.references?.length || 0)
    );
    const mentionCount = Number(result?.referencesVisual?.citations?.length || 0);
    const contextCount = Number(result?.referencesVisual?.contexts?.length || 0);
    const layerItemsCount = countLayerItems(result?.readerData?.layers);
    const hasPages = Array.isArray(result?.readerData?.pages) && result.readerData.pages.length > 0;
    const layerLabel = nextLayer
      ? (READER_V2_LAYER_LABELS[nextLayer] || nextLayer)
      : "sin capa activa";
    const layerCountLabel =
      nextLayer && Array.isArray(nextItems) ? nextItems.length : layerItemsCount;

    const baseMessage = `Extraccion completada. Referencias: ${referencesCount}. Citas enlazadas: ${mentionCount}. Contextos: ${contextCount}. Capas (${layerLabel}): ${layerCountLabel}.`;

    if (!referencesCount && !layerItemsCount && !hasPages) {
      return {
        tone: "warning",
        message: "Extraccion completada con datos insuficientes.",
        hint: "No se detecto texto seleccionable o la extraccion del PDF fue insuficiente para preparar Capas y Referencias.",
      };
    }
    if (!referencesCount) {
      return {
        tone: "warning",
        message: "Extraccion completada sin referencias detectadas.",
        hint: "Se han generado capas basicas, pero no se detectaron referencias bibliograficas en este PDF.",
      };
    }
    if (!mentionCount) {
      return {
        tone: "warning",
        message: "Extraccion completada.",
        hint: "Se detectaron referencias, pero no citas enlazables en el cuerpo del texto.",
      };
    }
    if (!layerItemsCount) {
      return {
        tone: "warning",
        message: "Extraccion completada.",
        hint: "No se detectaron capas visuales utilizables. Revisa si el PDF tiene texto seleccionable.",
      };
    }
    return {
      tone: "success",
      message: baseMessage,
      hint: "",
    };
  };

  const handleExtract = async () => {
    setExtractEnrichment(null);
    setReferenceDebugDownload(null);
    setExtractStatus({
      loading: true,
      error: "",
      message: "Extraccion en curso. Esto puede tardar unos segundos...",
      hint: "",
      tone: "loading",
    });
    const file = await ensurePdfFile();
    if (!file) {
      setExtractStatus({
        loading: false,
        error: "No hay PDF disponible para extraer.",
        message: "",
        hint: "",
        tone: "error",
      });
      return;
    }

    try {
      const fd = new FormData();
      fd.append("manuscript", file);
      fd.append("engine", PREVIEW_EXTRACT_ENGINE);
      fd.append(
        "debug_reference_detection",
        debugReferenceDetection ? "1" : "0"
      );
      fd.append("debug", debugReferenceDetection ? "1" : "0");
      const normalizedArticleDoi = String(articleDoiInput || "").trim();
      if (normalizedArticleDoi) {
        fd.append("article_doi", normalizedArticleDoi);
      }

      const res = await fetch(EXTRACT_ENDPOINT, { method: "POST", body: fd });
      const payload = await res.json().catch(() => null);
      if (!res.ok || !payload?.ok) {
        const rawError =
          payload?.error ||
          (res.status >= 500
            ? "Error interno durante la extraccion."
            : "No se pudo completar la extraccion.");
        setExtractStatus({
          loading: false,
          error: rawError,
          message: "",
          hint: "",
          tone: "error",
        });
        return;
      }

      const result = buildExtractionResult(payload);
      const enrichmentPayload =
        payload?.enrichment && typeof payload.enrichment === "object"
          ? payload.enrichment
          : null;
      const nextArticleInfo = normalizeArticleInfo(payload?.article_info);
      const payloadArticleDoi = normalizeDoi(
        payload?.article_doi || nextArticleInfo?.doi || ""
      );
      const referenceDebugMeta =
        payload?.reference_debug && typeof payload.reference_debug === "object"
          ? payload.reference_debug
          : null;
      const referenceDebugPath = String(
        referenceDebugMeta?.output_path || ""
      ).trim();
      const referenceDebugDownloadUrl = String(
        referenceDebugMeta?.download_url || ""
      ).trim();
      const referenceDebugFilename = String(
        referenceDebugMeta?.filename || ""
      ).trim();
      setSnippetsData(result.snippets);
      setReferencesData(result.references);
      setReferencesVisualData(result.referencesVisual);
      setExtractionExportData(buildExtractionExportData(payload, result, file));
      setReferenceDebugDownload(
        referenceDebugDownloadUrl
          ? {
              url: referenceDebugDownloadUrl,
              filename: referenceDebugFilename || "reference_debug.json",
            }
          : null
      );
      setExtractEnrichment(enrichmentPayload);
      setArticleInfo(nextArticleInfo);
      if (payloadArticleDoi) {
        setArticleDoiInput(payloadArticleDoi);
      }
      setSelectedReferenceId("");
      setHoveredReferenceId("");
      setSelectedCitationId("");
      setHoveredCitationId("");
      setStats(result.stats);
      const nextData = result.readerData;
      const nextLayer = pickDefaultReaderV2Layer(nextData);
      const nextItems =
        nextLayer && Array.isArray(nextData.layers?.[nextLayer])
          ? nextData.layers[nextLayer]
          : [];
      setReaderV2Data(nextData);
      setReaderV2Layer(nextLayer);
      setHoveredItemId(null);
      setSelectedItemId(null);
      setShowReaderV2(Boolean(nextLayer));
      setReaderV2Opacity(1);
      const nextDebugSteps = Array.isArray(payload?.reference_debug_steps)
        ? payload.reference_debug_steps
        : [];
      setRefDebugSteps(nextDebugSteps);
      setActiveRefDebugKeys(new Set());
      setShowRefDebug(false);
      setActiveTab("references");
      const outcome = describeExtractionOutcome(result, nextLayer, nextItems);
      const enrichmentHint =
        enrichmentPayload?.paper_resolved &&
        Number(enrichmentPayload?.references_enriched) > 0
          ? `Referencias enriquecidas mediante DOI: ${Number(
              enrichmentPayload.references_enriched
            )}.`
          : (enrichmentPayload?.warning === "invalid_doi"
            ? "DOI no valido; se uso extraccion local."
            : "");
      const debugHint = referenceDebugPath
        ? `Debug JSON: ${referenceDebugPath}.`
        : "";
      setExtractStatus({
        loading: false,
        error: "",
        message: outcome.message,
        hint: [outcome.hint, enrichmentHint, debugHint].filter(Boolean).join(" "),
        tone: outcome.tone,
      });
      if (payloadArticleDoi) {
        setArticleDoiLookup({
          loading: false,
          message: nextArticleInfo?.resolved
            ? "DOI del articulo confirmado y metadatos cargados."
            : "DOI del articulo disponible para esta extraccion.",
          tone: nextArticleInfo?.resolved ? "success" : "info",
        });
      }
    } catch (err) {
      setExtractStatus({
        loading: false,
        error: "Error de red al extraer.",
        message: "",
        hint: "Comprueba la conexion e intentalo de nuevo.",
        tone: "error",
      });
    }
  };

  const handleArticleDoiInputChange = (event) => {
    const nextValue = event.target.value;
    const normalized = normalizeDoi(nextValue);
    setArticleDoiInput(nextValue);
    setArticleInfo((current) => {
      const currentInfo = normalizeArticleInfo(current);
      if (currentInfo?.doi && currentInfo.doi === normalized) {
        return currentInfo;
      }
      return null;
    });
    setArticleDoiLookup((current) =>
      current.loading
        ? current
        : {
            loading: false,
            message: "",
            tone: "idle",
          }
    );
  };

  const detectArticleDoiFromPdf = async (file) => {
    if (!file) return;
    const requestId = articleDoiRequestIdRef.current + 1;
    articleDoiRequestIdRef.current = requestId;
    setArticleDoiLookup({
      loading: true,
      message: "Buscando DOI del articulo en el PDF...",
      tone: "info",
    });

    try {
      const fd = new FormData();
      fd.append("manuscript", file);
      const res = await fetch(DETECT_ARTICLE_DOI_ENDPOINT, {
        method: "POST",
        body: fd,
      });
      const payload = await res.json().catch(() => null);
      if (articleDoiRequestIdRef.current !== requestId) {
        return;
      }
      if (!res.ok || !payload?.ok) {
        setArticleDoiLookup({
          loading: false,
          message: "No se pudo detectar automaticamente el DOI del articulo.",
          tone: "warning",
        });
        return;
      }

      const nextArticleInfo = normalizeArticleInfo(payload?.article_info);
      const detectedDoi = normalizeDoi(
        payload?.article_doi || nextArticleInfo?.doi || ""
      );
      setArticleInfo(nextArticleInfo);
      if (detectedDoi) {
        setArticleDoiInput(detectedDoi);
        setArticleDoiLookup({
          loading: false,
          message: nextArticleInfo?.resolved
            ? "DOI detectado automaticamente y metadatos listos."
            : "DOI detectado automaticamente al cargar el PDF.",
          tone: "success",
        });
        return;
      }

      setArticleDoiLookup({
        loading: false,
        message: "No se detecto DOI automaticamente en este PDF.",
        tone: "warning",
      });
    } catch (error) {
      if (articleDoiRequestIdRef.current !== requestId) {
        return;
      }
      setArticleDoiLookup({
        loading: false,
        message: "No se pudo comprobar el DOI automaticamente.",
        tone: "warning",
      });
    }
  };

  const handleViewReference = (ref) => {
    const numericIndex = Number(ref?.index);
    const refId =
      String(ref?.ref_id || "").trim() ||
      (Number.isFinite(numericIndex) && numericIndex > 0
        ? `ref-${numericIndex}`
        : "");
    if (refId) {
      jumpToReference(refId);
      setActiveReferenceId(numericIndex || null);
      setHighlightReferenceId(numericIndex || null);
      setSelectedReferenceId(refId);
      setSelectedCitationId("");
    }
    const extractorSnippet = referenceSnippetByIndex.get(ref.index);
    const inlineSnippet = inlineSnippetByIndex.get(ref.index);
    const linkedSnippet = extractorSnippet || inlineSnippet;
    if (linkedSnippet) {
      const snippetPayload = linkedSnippet.snippet
        ? linkedSnippet
        : { snippet: String(linkedSnippet || "") };
      setSelectedSnippet({
        ...snippetPayload,
        id: linkedSnippet.id || `inline-${ref.index}`,
        page: inlineSnippet?.page || ref.display_page || linkedSnippet.page || null,
        type: linkedSnippet.type || "bracket",
        confidence: linkedSnippet.confidence || 0,
        reference_index: ref.index,
        highlight_snippet: inlineSnippet?.snippet || "",
        highlightMode: "paragraph",
      });
      setSelectedSnippetAnchor(null);
    }
  };

  const handleReferenceSelect = (ref) => {
    const numericIndex = Number(ref?.index);
    const refId =
      String(ref?.ref_id || "").trim() ||
      (Number.isFinite(numericIndex) && numericIndex > 0
        ? `ref-${numericIndex}`
        : "");
    setActiveReferenceKey(refId || referenceKey(ref));
    setActiveReferenceId(numericIndex || null);
    setHighlightReferenceId(numericIndex || null);
    if (refId) {
      setSelectedReferenceId(refId);
    }
    setSelectedCitationId("");
    const visualReference = refId ? referencesByRefId.get(refId) : null;
    if (visualReference) {
      scrollReferenceTargetToTop(visualReference);
    }
    const extractorSnippet = referenceSnippetByIndex.get(ref.index);
    const inlineSnippet = inlineSnippetByIndex.get(ref.index);
    const linkedSnippet = extractorSnippet || inlineSnippet;
    if (linkedSnippet) {
      const snippetPayload = linkedSnippet.snippet
        ? linkedSnippet
        : { snippet: String(linkedSnippet || "") };
      setSelectedSnippet({
        ...snippetPayload,
        id: linkedSnippet.id || `inline-${ref.index}`,
        page: inlineSnippet?.page || ref.display_page || linkedSnippet.page || null,
        type: linkedSnippet.type || "bracket",
        confidence: linkedSnippet.confidence || 0,
        reference_index: ref.index,
        highlight_snippet: inlineSnippet?.snippet || "",
        highlightMode: "paragraph",
      });
      setSelectedSnippetAnchor(null);
    }
    const statsEntry = citationStatsByReference.get(ref.index);
    if (!visualReference && statsEntry && statsEntry.pages.size) {
      const pages = Array.from(statsEntry.pages).sort((a, b) => a - b);
      if (pages[0]) {
        scrollReferenceTargetToTop(null, pages[0] - 1);
      }
    }
  };

  const handleReferenceOverlayHover = (item) => {
    if (!item) {
      setHoveredReferenceId("");
      setHoveredCitationId("");
      return;
    }
    setHoveredReferenceId(String(item.refId || item.ref_id || ""));
    setHoveredCitationId(
      String(item.itemType || item.item_type) === "citation-mention"
        ? String(item.id || "")
        : ""
    );
  };

  const handleReferenceOverlaySelect = (item) => {
    if (!item) return;
    const refId = String(item.refId || item.ref_id || "");
    if (!refId) return;
    setSelectedReferenceId(refId);
    setActiveReferenceKey(refId);
    if (String(item.itemType || item.item_type) === "citation-mention") {
      setSelectedCitationId(String(item.id || ""));
    } else {
      setSelectedCitationId("");
    }
    const indexFromRefId = parseRefIndex(refId);
    if (Number.isFinite(indexFromRefId)) {
      setActiveReferenceId(indexFromRefId);
      setHighlightReferenceId(indexFromRefId);
    }
    jumpToReference(refId);
  };

  const handleReferenceMentionSelect = (mention, refId) => {
    const resolvedRefId = String(refId || mention?.ref_id || "").trim();
    if (!resolvedRefId) return;
    setSelectedReferenceId(resolvedRefId);
    setActiveReferenceKey(resolvedRefId);
    setHoveredReferenceId(resolvedRefId);
    setSelectedCitationId(String(mention?.id || ""));
    const indexFromRefId = parseRefIndex(resolvedRefId);
    if (Number.isFinite(indexFromRefId)) {
      setActiveReferenceId(indexFromRefId);
      setHighlightReferenceId(indexFromRefId);
    }
    if (mention) {
      scrollReferenceTargetToTop(mention);
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

  useEffect(() => {
    if (!selectedReferenceId) return;
    const sideTimer = window.setTimeout(() => {
      scrollReferenceRowToTop(selectedReferenceId);
    }, 120);
    const mentions = citationMentionsByRefId.get(selectedReferenceId) || [];
    const contexts = citationContextsByRefId.get(selectedReferenceId) || [];
    const refRow = referencesByRefId.get(selectedReferenceId) || null;
    const selectedMention = mentions.find(
      (mention) => String(mention?.id || "") === String(selectedCitationId || "")
    );
    if (selectedMention) {
      scrollReferenceTargetToTop(selectedMention);
    } else if (refRow) {
      scrollReferenceTargetToTop(refRow);
    } else {
      const fallbackTarget = contexts[0] || mentions[0] || null;
      if (fallbackTarget) {
        scrollReferenceTargetToTop(fallbackTarget);
      }
    }
    return () => {
      window.clearTimeout(sideTimer);
    };
  }, [
    selectedReferenceId,
    selectedCitationId,
    citationMentionsByRefId,
    citationContextsByRefId,
    referencesByRefId,
    scrollReferenceRowToTop,
    scrollReferenceTargetToTop,
  ]);

  const applyPdfFile = (file) => {
    if (!file) return;
    if (file.type !== "application/pdf") {
      setExtractStatus({
        loading: false,
        error: "Selecciona un PDF valido.",
        message: "",
        hint: "",
        tone: "error",
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
    setReferencesVisualData({
      references: [],
      citations: [],
      contexts: [],
      citation_style: "",
      max_reference_index: null,
      bibliography_start_page: null,
    });
    setExtractEnrichment(null);
    setArticleInfo(null);
    setArticleDoiInput("");
    setArticleDoiLookup({
      loading: true,
      message: "Buscando DOI del articulo en el PDF...",
      tone: "info",
    });
    setExtractionExportData(null);
    setReferenceDebugDownload(null);
    setSelectedReferenceId("");
    setHoveredReferenceId("");
    setSelectedCitationId("");
    setHoveredCitationId("");
    setStats(null);
    setSelectedSnippet(null);
    setSelectedSnippetAnchor(null);
    setSelectedSnippetPopoverStyle(null);
    setActiveCitation(null);
    setReaderV2Data(null);
    setReaderV2Layer("");
    setHoveredItemId(null);
    setSelectedItemId(null);
    setShowReaderV2(false);
    setReaderV2Opacity(1);
    setExtractStatus({
      loading: false,
      error: "",
      message: "PDF cargado correctamente.",
      hint: 'Pulsa "Extraer" para preparar Capas y Referencias.',
      tone: "idle",
    });
    detectArticleDoiFromPdf(file);
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
    articleDoiRequestIdRef.current += 1;
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
    setReaderV2Data(null);
    setReferencesVisualData({
      references: [],
      citations: [],
      contexts: [],
      citation_style: "",
      max_reference_index: null,
      bibliography_start_page: null,
    });
    setExtractEnrichment(null);
    setArticleInfo(null);
    setArticleDoiInput(String(reportOriginalDoi || "").trim());
    setArticleDoiLookup({
      loading: false,
      message: "",
      tone: "idle",
    });
    setExtractionExportData(null);
    setReferenceDebugDownload(null);
    setSelectedReferenceId("");
    setHoveredReferenceId("");
    setSelectedCitationId("");
    setHoveredCitationId("");
    setReaderV2Layer("");
    setHoveredItemId(null);
    setSelectedItemId(null);
    setShowReaderV2(false);
    setReaderV2Opacity(1);
    setExtractStatus({
      loading: false,
      error: "",
      message: "PDF eliminado.",
      hint: "",
      tone: "idle",
    });
  };

  const dropzoneLabel = useMemo(() => {
    if (!activeFile) {
      return "Arrastra un PDF aqui o haz clic para seleccionarlo";
    }
    const sizeKb = Math.round(activeFile.size / 1024);
    return `${activeFile.name} - ${sizeKb} KB`;
  }, [activeFile]);

  const readerV2Controls = (
    <div className="reader-v2-controls">
      <div className={`reader-panel-status is-${layersPanelNotice.tone}`}>
        {layersPanelNotice.text}
      </div>
      <label className="reader-v2-layer">
        <span className="reader-v2-layer-label">Capa</span>
        <select
          className="reader-engine-select"
          value={activeReaderV2Layer}
          disabled={!readerV2LayerOptions.length}
          onChange={(event) => setReaderV2Layer(event.target.value)}
        >
          {!readerV2LayerOptions.length && (
            <option value="">Sin capas disponibles</option>
          )}
          {readerV2LayerOptions.map((layerName) => (
            <option key={layerName} value={layerName}>
              {READER_V2_LAYER_LABELS[layerName] || layerName}
            </option>
          ))}
        </select>
      </label>
      <div className="reader-v2-items-panel">
        <div className="reader-v2-items-header">
          <span>Elementos de la capa</span>
          <span className="reader-v2-items-count">{currentLayerItems.length}</span>
        </div>
        {!currentLayerItems.length ? (
          <div className="reader-empty-inline">No hay elementos para la capa seleccionada.</div>
        ) : (
          <div className="reader-v2-items-list">
            {currentLayerItems.map((item, index) => {
              const itemId = item.__v2id;
              const itemText = String(item?.text || "");
              const pageValue = Number(item?.page);
              const pageLabel = Number.isFinite(pageValue) ? pageValue + 1 : "-";
              const isHovered = hoveredItemId === itemId;
              const isSelected = selectedItemId === itemId;
              return (
                <button
                  key={itemId}
                  ref={registerReaderV2ItemRow(itemId)}
                  type="button"
                  className={[
                    "reader-v2-item",
                    isHovered ? "is-hovered" : "",
                    isSelected ? "is-selected" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  title={itemText}
                  onMouseEnter={() => handleReaderV2ItemHover(itemId)}
                  onMouseLeave={() => handleReaderV2ItemHover(null)}
                  onClick={() => handleReaderV2ItemSelect(itemId)}
                >
                  <span className="reader-v2-item-index">{index + 1}</span>
                  <span className="reader-v2-item-main">
                    <span className="reader-v2-item-text">{itemText || "(sin texto)"}</span>
                    <span className="reader-v2-item-meta">p. {pageLabel}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <label className="reader-v2-toggle">
        <input
          type="checkbox"
          checked={showReaderV2}
          disabled={!activeReaderV2Layer}
          onChange={(event) => setShowReaderV2(event.target.checked)}
        />
        Mostrar overlay
      </label>
      <div className="reader-muted">
        Capa activa:{" "}
        {activeReaderV2Layer
          ? (READER_V2_LAYER_LABELS[activeReaderV2Layer] || activeReaderV2Layer)
          : "-"}
      </div>
      <div className="reader-v2-opacity">
        Opacidad: {Math.round(readerV2Opacity * 100)}%
      </div>
      <input
        type="range"
        min="0.1"
        max="1"
        step="0.05"
        className="reader-v2-slider"
        value={readerV2Opacity}
        disabled={!showReaderV2 || !activeReaderV2Layer}
        onChange={(event) => setReaderV2Opacity(Number(event.target.value))}
      />
      {readerV2Data && (
        <div className="reader-muted">
          Paginas: {readerV2PagesTotal} | Capa activa: {readerV2ItemsTotal} | Total capas:{" "}
          {readerV2AllItemsTotal}
        </div>
      )}

      {refDebugSteps.length > 0 && (
        <div className="ref-debug-section">
          <div className="ref-debug-header">
            <span className="ref-debug-title">Reference Debug</span>
            <label className="ref-debug-master-toggle">
              <input
                type="checkbox"
                checked={showRefDebug}
                onChange={(event) => setShowRefDebug(event.target.checked)}
              />
              Mostrar
            </label>
          </div>
          <div className="ref-debug-steps">
            {refDebugSteps.map((step) => {
              const color = REF_DEBUG_STEP_COLORS[step.key] || REF_DEBUG_STEP_DEFAULT_COLOR;
              const isActive = activeRefDebugKeys.has(step.key);
              const itemCount = (step.items || []).length;
              return (
                <label
                  key={step.key}
                  className={`ref-debug-step${isActive ? " is-active" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={isActive}
                    onChange={(event) => {
                      setActiveRefDebugKeys((prev) => {
                        const next = new Set(prev);
                        if (event.target.checked) next.add(step.key);
                        else next.delete(step.key);
                        return next;
                      });
                    }}
                  />
                  <span
                    className="ref-debug-swatch"
                    style={{ background: color.stroke }}
                  />
                  <span className="ref-debug-step-label">{step.label}</span>
                  <span className="ref-debug-step-count">{itemCount}</span>
                </label>
              );
            })}
          </div>
          {showRefDebug && activeRefDebugKeys.size > 0 && (
            <>
              <div className="reader-v2-opacity">
                Opacidad debug: {Math.round(refDebugOpacity * 100)}%
              </div>
              <input
                type="range"
                min="0.1"
                max="1"
                step="0.05"
                className="reader-v2-slider"
                value={refDebugOpacity}
                onChange={(event) => setRefDebugOpacity(Number(event.target.value))}
              />
            </>
          )}
        </div>
      )}
    </div>
  );

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
      <div className="reader-muted">Motor: PaperMage (unificado)</div>
      <label className="reader-v2-layer">
        <span className="reader-v2-layer-label">DOI del articulo</span>
        <input
          type="text"
          className="reader-engine-select"
          value={articleDoiInput}
          onChange={handleArticleDoiInputChange}
          placeholder="10.xxxx/xxxxx"
        />
      </label>
      <div className="reader-muted">
        Opcional: anade el DOI del articulo para mejorar la precision de las referencias.
      </div>
      {(articleDoiLookup.loading || articleDoiLookup.message) && (
        <div
          className={
            articleDoiLookup.loading
              ? "reader-panel-status"
              : articleDoiLookup.tone === "warning"
                ? "reader-panel-status is-warning"
                : articleDoiLookup.tone === "success"
                  ? "reader-panel-status is-success"
                  : "reader-panel-status"
          }
        >
          {articleDoiLookup.loading
            ? "Buscando DOI del articulo en el PDF..."
            : articleDoiLookup.message}
        </div>
      )}
      {extractEnrichment?.paper_resolved &&
        Number(extractEnrichment?.references_enriched) > 0 && (
          <div className="reader-muted">
            Referencias enriquecidas mediante DOI ({Number(
              extractEnrichment.references_enriched
            )}).
          </div>
        )}
      <div className="reader-extract-actions">
        <button
          type="button"
          className="reader-tool-btn"
          onClick={handleExtract}
          disabled={!canExtract}
        >
          {extractStatus.loading
            ? `Extrayendo... ${Math.round(extractProgress.value || 0)}%`
            : "Extraer"}
        </button>
        <button
          type="button"
          className="reader-tool-btn"
          onClick={() => downloadExtractionJson(extractionExportData)}
          disabled={!canDownloadExtraction}
        >
          Descargar
        </button>
        <button
          type="button"
          className="reader-tool-btn"
          onClick={() => downloadReferenceDebugJson(referenceDebugDownload)}
          disabled={!canDownloadDebug}
        >
          Descargar depuracion
        </button>
      </div>
      <label className="reader-extract-debug-toggle">
        <input
          type="checkbox"
          checked={debugReferenceDetection}
          onChange={(event) => setDebugReferenceDetection(event.target.checked)}
        />
        <span>Guardar JSON de depuracion de referencias</span>
      </label>
      {extractStatus.loading && (
        <div className="reader-extract-progress" role="status" aria-live="polite">
          <div className="reader-extract-progress-head">
            <span className="reader-extract-progress-spinner" aria-hidden="true" />
            <div className="reader-extract-progress-copy">
              <div className="reader-extract-progress-label">
                {extractProgress.label || "Preparando extraccion..."}
              </div>
              <div className="reader-extract-progress-meta">
                Progreso aproximado
              </div>
            </div>
            <div className="reader-extract-progress-value">
              {Math.round(extractProgress.value || 0)}%
            </div>
          </div>
          <div className="reader-extract-progress-track" aria-hidden="true">
            <div
              className="reader-extract-progress-fill"
              style={{
                width: `${Math.max(4, Math.round(extractProgress.value || 0))}%`,
              }}
            />
          </div>
        </div>
      )}
      {(extractStatus.error || extractStatus.message || extractStatus.hint) && (
        <div
          className={
            extractStatus.error
              ? "reader-extract-status is-error"
              : extractStatus.tone === "warning"
                ? "reader-extract-status is-warning"
                : extractStatus.tone === "success"
                  ? "reader-extract-status is-success"
                  : "reader-extract-status"
          }
        >
          <div>{extractStatus.error || extractStatus.message}</div>
          {extractStatus.hint && (
            <div className="reader-extract-status-hint">{extractStatus.hint}</div>
          )}
        </div>
      )}
    </div>
  );

  const tabsBar = (
    <div className="reader-tabs">
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
      {hasArticleInfoTab && (
        <button
          type="button"
          className={
            activeTab === "info"
              ? "reader-tab is-active"
              : "reader-tab"
          }
          onClick={() => setActiveTab("info")}
        >
          Info
        </button>
      )}
      <button
        type="button"
        className={
          activeTab === "v2"
            ? "reader-tab is-active"
            : "reader-tab"
        }
        onClick={() => setActiveTab("v2")}
      >
        Capas
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
        Referencias
      </button>
    </div>
  );

  return (
    <div className="reader-app">
      <aside className="reader-sidebar">
        {activeTab === "snippets" && (
          <div className="reader-card reader-panel">
            {tabsBar}
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
            {tabsBar}
            <div className="reader-ref-header">
              <div className="reader-card-title">Referencias</div>
              <div className="reader-muted">{referenceRows.length} total</div>
            </div>
            <div className="reader-ref-metrics">
              <span className="reader-pill">Refs: {visualReferenceTotal || referenceRows.length}</span>
              <span className="reader-pill">Citas: {visualCitationTotal}</span>
              <span className="reader-pill">Contextos: {visualContextTotal}</span>
            </div>
            <div className={`reader-panel-status is-${referencesPanelNotice.tone}`}>
              {referencesPanelNotice.text}
            </div>
            <div className="reader-search">
              <input
                type="search"
                value={referenceQuery}
                onChange={(event) => setReferenceQuery(event.target.value)}
                placeholder="Buscar referencias"
                className="reader-search-input"
              />
            </div>
            {referenceRows.length === 0 ? (
              <div className="reader-empty-inline">
                No hay referencias disponibles para mostrar.
              </div>
            ) : filteredReferenceRows.length === 0 ? (
              <div className="reader-empty-inline">
                No hay referencias que coincidan con la busqueda.
              </div>
            ) : (
              filteredReferenceRows.map((row) => {
                const isActive = row.ref_id === selectedReferenceId;
                const rowMentions = isActive ? selectedReferenceMentions : [];
                const pageLabel = Number.isFinite(Number(row.page))
                  ? `p. ${Number(row.page) + 1}`
                  : "p. -";
                return (
                  <div
                    key={row.ref_id}
                    ref={registerReference(row.ref_id)}
                    role="button"
                    tabIndex={0}
                    className={
                      isActive
                        ? "reader-ref-row is-active"
                        : "reader-ref-row"
                    }
                    onMouseEnter={() => setHoveredReferenceId(row.ref_id)}
                    onMouseLeave={() => {
                      setHoveredReferenceId("");
                      setHoveredCitationId("");
                    }}
                    onClick={() =>
                      handleReferenceSelect({
                        ...(referenceByIndex.get(row.index) || {}),
                        ref_id: row.ref_id,
                        index: row.index,
                        raw: row.text,
                        display_page:
                          Number.isFinite(Number(row.page)) ? Number(row.page) + 1 : null,
                      })
                    }
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        handleReferenceSelect({
                          ...(referenceByIndex.get(row.index) || {}),
                          ref_id: row.ref_id,
                          index: row.index,
                          raw: row.text,
                          display_page:
                            Number.isFinite(Number(row.page)) ? Number(row.page) + 1 : null,
                        });
                      }
                    }}
                  >
                    <div className="reader-ref-top">
                      <span className="reader-ref-index">
                        {row.index ? `#${row.index}` : "-"}
                      </span>
                      <span className="reader-ref-page">
                        {pageLabel} | menciones: {row.mentions_total}
                      </span>
                    </div>
                    <div
                      className={
                        row.text
                          ? "reader-ref-snippet"
                          : "reader-ref-snippet is-muted"
                      }
                    >
                      <span
                        className={
                          isActive
                            ? "reader-ref-snippet-text is-expanded"
                            : "reader-ref-snippet-text"
                        }
                      >
                        {row.text ? `"${row.text}"` : "\"Sin texto de referencia.\""}
                      </span>
                    </div>
                    <div className="reader-ref-footer">
                      <div className="reader-ref-footer-main">
                        <span className="reader-ref-title">
                          {row.title || "Sin titulo"}
                        </span>
                        {row.author && (
                          <span className="reader-ref-author"> - {row.author}</span>
                        )}
                      </div>
                      {row.structure_source && (
                        <div className="reader-ref-meta">
                          structure_source: {row.structure_source}
                        </div>
                      )}
                      {row.doi && <div className="reader-ref-doi">DOI: {row.doi}</div>}
                    </div>
                    {isActive && rowMentions.length > 0 && (
                      <div className="reader-ref-mentions">
                        <div className="reader-ref-mentions-title">
                          Menciones ({rowMentions.length})
                        </div>
                        {rowMentions.map((mention, mentionIndex) => {
                          const mentionId = String(mention?.id || "");
                          const mentionPageValue = Number(mention?.page);
                          const mentionPageLabel = Number.isFinite(mentionPageValue)
                            ? `p. ${mentionPageValue + 1}`
                            : "p. -";
                          const mentionText = String(mention?.text || "").trim();
                          const isSelectedMention =
                            mentionId &&
                            mentionId === String(selectedCitationId || "");
                          return (
                            <button
                              type="button"
                              key={mentionId || `${row.ref_id}-mention-${mentionIndex}`}
                              className={
                                isSelectedMention
                                  ? "reader-ref-mention is-active"
                                  : "reader-ref-mention"
                              }
                              onMouseEnter={() => {
                                setHoveredReferenceId(row.ref_id);
                                setHoveredCitationId(mentionId);
                              }}
                              onMouseLeave={() => setHoveredCitationId("")}
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                handleReferenceMentionSelect(mention, row.ref_id);
                              }}
                            >
                              <span className="reader-ref-mention-meta">
                                {mentionPageLabel}
                              </span>
                              <span className="reader-ref-mention-text">
                                {mentionText || "Cita sin texto disponible."}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === "info" && hasArticleInfoTab && (
          <div className="reader-card reader-panel">
            {tabsBar}
            <div className="reader-ref-header">
              <div className="reader-card-title">Info del articulo</div>
              <div className="reader-muted">
                {effectiveArticleInfo?.resolved ? "DOI resuelto" : "DOI disponible"}
              </div>
            </div>
            <div
              className={
                effectiveArticleInfo?.resolved
                  ? "reader-panel-status is-success"
                  : "reader-panel-status"
              }
            >
              {effectiveArticleInfo?.resolved
                ? "Metadatos del articulo cargados a partir del DOI."
                : "Hay DOI del articulo, pero no se han recuperado mas metadatos todavia."}
            </div>
            <div className="reader-info-grid">
              <div className="reader-info-card reader-info-card--wide">
                <div className="reader-info-label">DOI</div>
                <div className="reader-info-value reader-info-value--doi">
                  {effectiveArticleInfo?.doi || "-"}
                </div>
                <div className="reader-info-actions">
                  <a
                    className="reader-action"
                    href={effectiveArticleInfo?.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Abrir DOI
                  </a>
                  <button
                    type="button"
                    className="reader-action"
                    onClick={() => copyToClipboard(effectiveArticleInfo?.doi || "")}
                  >
                    Copiar DOI
                  </button>
                </div>
              </div>
              <div className="reader-info-card reader-info-card--wide">
                <div className="reader-info-label">Titulo</div>
                <div className="reader-info-title">
                  {effectiveArticleInfo?.title || "Sin titulo resuelto"}
                </div>
              </div>
              <div className="reader-info-card">
                <div className="reader-info-label">Autores</div>
                <div className="reader-info-value">
                  {effectiveArticleInfo?.authors?.length
                    ? effectiveArticleInfo.authors.join(", ")
                    : "Sin autores resueltos"}
                </div>
              </div>
              <div className="reader-info-card">
                <div className="reader-info-label">Venue</div>
                <div className="reader-info-value">
                  {effectiveArticleInfo?.venue || "Sin venue resuelto"}
                </div>
              </div>
              <div className="reader-info-card">
                <div className="reader-info-label">Ano</div>
                <div className="reader-info-value">
                  {effectiveArticleInfo?.year || "-"}
                </div>
              </div>
              <div className="reader-info-card">
                <div className="reader-info-label">Referencias DOI</div>
                <div className="reader-info-value">
                  {Number(effectiveArticleInfo?.references_count || 0)}
                </div>
              </div>
              <div className="reader-info-card">
                <div className="reader-info-label">Citado por</div>
                <div className="reader-info-value">
                  {Number(effectiveArticleInfo?.cited_by_count || 0)}
                </div>
              </div>
              <div className="reader-info-card">
                <div className="reader-info-label">Fuente principal</div>
                <div className="reader-info-value">
                  {effectiveArticleInfo?.source || "doi"}
                </div>
              </div>
            </div>
            {effectiveArticleInfo?.sources_used?.length > 0 && (
              <div className="reader-ref-metrics">
                {effectiveArticleInfo.sources_used.map((source) => (
                  <span className="reader-pill" key={source}>
                    {source}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "stats" && (
          <div className="reader-card reader-panel">
            {tabsBar}
            <div className="reader-card-title">Stats</div>
            <div className="reader-stats">
              <div className="reader-stat-card">
                <div className="reader-stat-label">Report ID</div>
                <div className="reader-stat-value">{reportId || "n/a"}</div>
              </div>
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
            {loading && <div className="reader-muted">Loading data...</div>}
            {error && <div className="reader-error">{error}</div>}
            {BUILD_ID && <div className="reader-muted">Build: {BUILD_ID}</div>}
          </div>
        )}

        {activeTab === "v2" && (
          <div className="reader-card reader-panel">
            {tabsBar}
            <div className="reader-card-title">Capas</div>
            {readerV2Controls}
          </div>
        )}

        {activeTab === "extract" && (
          <div className="reader-card reader-panel">
            {tabsBar}
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
            evidenceUrl={evidenceUrl}
            selectedMention={selectedSnippet}
            onHighlight={handleHighlight}
            viewerRef={viewerRef}
            readerV2Data={readerV2Data}
            readerV2Layer={activeReaderV2Layer}
            readerV2LayerItems={currentLayerOverlayItems}
            showReaderV2={showReaderV2}
            readerV2Opacity={readerV2Opacity}
            hoveredItemId={hoveredItemId}
            selectedItemId={selectedItemId}
            onHoverItemChange={handleReaderV2ItemHover}
            onSelectItem={handleReaderV2ItemSelect}
            referenceOverlayVisible={activeTab === "references"}
            referenceOverlayItems={referencesOverlayItems}
            selectedReferenceId={selectedReferenceId}
            hoveredReferenceId={hoveredReferenceId}
            selectedCitationId={selectedCitationId}
            hoveredCitationId={hoveredCitationId}
            onReferenceOverlayHover={handleReferenceOverlayHover}
            onReferenceOverlaySelect={handleReferenceOverlaySelect}
            refDebugSteps={refDebugSteps}
            activeRefDebugKeys={activeRefDebugKeys}
            showRefDebug={showRefDebug}
            refDebugOpacity={refDebugOpacity}
          />

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
