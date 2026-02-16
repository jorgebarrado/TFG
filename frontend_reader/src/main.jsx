import React from "react";
import ReactDOM from "react-dom";
import ReaderApp from "./reader-app.jsx";
import "./styles.css";

const mount = document.getElementById("reader-root");
let previewFile = null;
let previewSnippets = [];
let previewStats = null;
let previewReferences = [];

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
      data.stats
    ) {
      previewSnippets = Array.isArray(data.snippets) ? data.snippets : [];
      previewStats = data.stats || null;
      previewReferences = Array.isArray(data.references) ? data.references : [];
      window.dispatchEvent(
        new CustomEvent("reader:data", {
          detail: {
            snippets: previewSnippets,
            stats: previewStats,
            references: previewReferences,
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
if (mount) {
  const apiUrl = mount.dataset.apiUrl || "";
  const pdfUrl = mount.dataset.pdfUrl || "";
  const reportId = mount.dataset.reportId || "";
  const reportOriginalDoi = mount.dataset.originalDoi || "";
  const reportIncorrectDoi = mount.dataset.incorrectDoi || "";
  ReactDOM.render(
    <ReaderApp
      apiUrl={apiUrl}
      pdfUrl={pdfUrl}
      reportId={reportId}
      reportOriginalDoi={reportOriginalDoi}
      reportIncorrectDoi={reportIncorrectDoi}
      previewFile={previewFile}
      previewSnippets={previewSnippets}
      previewStats={previewStats}
      previewReferences={previewReferences}
    />,
    mount
  );
}
