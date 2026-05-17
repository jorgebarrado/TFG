import React from "react";
import ReactDOM from "react-dom";
import ReaderApp from "./reader-app.jsx";
import "./styles.css";

const mount = document.getElementById("reader-root");
let previewFile = null;
let previewSnippets = [];
let previewStats = null;
let previewReferences = [];
let previewEnrichment = null;
let previewArticleInfo = null;
const READER_PAYLOAD_DB = "citecheck-reader-payloads";
const READER_PAYLOAD_STORE = "payloads";
const READER_PAYLOAD_SESSION_KEY = "citecheck.reader.payload";

function getPayloadKeyFromUrl() {
  try {
    const url = new URL(window.location.href);
    return String(url.searchParams.get("payload") || "").trim();
  } catch (e) {
    return "";
  }
}

function clearPayloadKeyFromUrl() {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("payload")) return;
    url.searchParams.delete("payload");
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(window.history.state, "", next);
  } catch (e) {
    // noop
  }
}

function openPayloadDb() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error("indexeddb_unavailable"));
      return;
    }
    const req = window.indexedDB.open(READER_PAYLOAD_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(READER_PAYLOAD_STORE)) {
        db.createObjectStore(READER_PAYLOAD_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("indexeddb_open_failed"));
  });
}

function readPayloadFileFromDb(db, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(READER_PAYLOAD_STORE, "readonly");
    const req = tx.objectStore(READER_PAYLOAD_STORE).get(key);
    req.onsuccess = () => resolve(req.result?.file || null);
    req.onerror = () => reject(req.error || new Error("indexeddb_read_failed"));
  });
}

function deletePayloadFromDb(db, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(READER_PAYLOAD_STORE, "readwrite");
    tx.objectStore(READER_PAYLOAD_STORE).delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error("indexeddb_delete_failed"));
  });
}

function readPayloadDataFromSession(key) {
  try {
    const raw = window.sessionStorage.getItem(`${READER_PAYLOAD_SESSION_KEY}:${key}`);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function clearPayloadDataFromSession(key) {
  try {
    window.sessionStorage.removeItem(`${READER_PAYLOAD_SESSION_KEY}:${key}`);
  } catch (e) {
    // noop
  }
}

async function bootstrapStoredPayload() {
  const payloadKey = getPayloadKeyFromUrl();
  if (!payloadKey) return;

  const sessionPayload = readPayloadDataFromSession(payloadKey);
  if (sessionPayload && typeof sessionPayload === "object") {
    previewSnippets = Array.isArray(sessionPayload.snippets)
      ? sessionPayload.snippets
      : [];
    previewStats = sessionPayload.stats || null;
    previewReferences = Array.isArray(sessionPayload.references)
      ? sessionPayload.references
      : [];
    previewEnrichment =
      sessionPayload.enrichment && typeof sessionPayload.enrichment === "object"
        ? sessionPayload.enrichment
        : null;
    previewArticleInfo =
      sessionPayload.articleInfo && typeof sessionPayload.articleInfo === "object"
        ? sessionPayload.articleInfo
        : null;
  }

  try {
    const db = await openPayloadDb();
    previewFile = await readPayloadFileFromDb(db, payloadKey);
    await deletePayloadFromDb(db, payloadKey);
    db.close();
  } catch (e) {
    previewFile = null;
  } finally {
    clearPayloadDataFromSession(payloadKey);
    clearPayloadKeyFromUrl();
  }
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  const data = event.data || {};
  if (data.type === "reader:payload") {
    if (data.file) {
      previewFile = data.file;
      window.dispatchEvent(
        new CustomEvent("reader:file-ready", { detail: { file: data.file } })
      );
    }
    if (
      Array.isArray(data.snippets) ||
      Array.isArray(data.references) ||
      data.stats ||
      data.enrichment ||
      data.articleInfo
    ) {
      previewSnippets = Array.isArray(data.snippets) ? data.snippets : [];
      previewStats = data.stats || null;
      previewReferences = Array.isArray(data.references) ? data.references : [];
      previewEnrichment =
        data.enrichment && typeof data.enrichment === "object"
          ? data.enrichment
          : null;
      previewArticleInfo =
        data.articleInfo && typeof data.articleInfo === "object"
          ? data.articleInfo
          : null;
      window.dispatchEvent(
        new CustomEvent("reader:data", {
          detail: {
            snippets: previewSnippets,
            stats: previewStats,
            references: previewReferences,
            enrichment: previewEnrichment,
            article_info: previewArticleInfo,
          },
        })
      );
    }
    return;
  }
  if (data.type === "reader:pdf-file" && data.file) {
    previewFile = data.file;
    window.dispatchEvent(
      new CustomEvent("reader:file-ready", { detail: { file: data.file } })
    );
  }
});

function notifyReady() {
  try {
    if (window.opener) {
      window.opener.postMessage(
        { type: "reader:ready" },
        window.location.origin
      );
    }
  } catch (e) {
    // noop
  }
}

if (document.readyState === "complete") {
  notifyReady();
} else {
  window.addEventListener("load", notifyReady);
}
function renderReaderApp() {
  if (!mount) return;
  const apiUrl = mount.dataset.apiUrl || "";
  const pdfUrl = mount.dataset.pdfUrl || "";
  const reportId = mount.dataset.reportId || "";
  const evidenceUrl = mount.dataset.evidenceUrl || "";
  const reportOriginalDoi = mount.dataset.originalDoi || "";
  const reportIncorrectDoi = mount.dataset.incorrectDoi || "";
  ReactDOM.render(
    <ReaderApp
      apiUrl={apiUrl}
      pdfUrl={pdfUrl}
      reportId={reportId}
      evidenceUrl={evidenceUrl}
      reportOriginalDoi={reportOriginalDoi}
      reportIncorrectDoi={reportIncorrectDoi}
      previewFile={previewFile}
      previewSnippets={previewSnippets}
      previewStats={previewStats}
      previewReferences={previewReferences}
      previewEnrichment={previewEnrichment}
      previewArticleInfo={previewArticleInfo}
    />,
    mount
  );
}

bootstrapStoredPayload().finally(renderReaderApp);
