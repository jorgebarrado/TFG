import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import test from "node:test";

const moduleUrl = pathToFileURL(
  "tfg_project/citations/static/js/extract_modal.js"
).href;

function installMinimalDom() {
  globalThis.document = {
    getElementById() {
      return null;
    },
  };
}

test("renders references_data as a reader-like references panel", async () => {
  installMinimalDom();
  delete globalThis.__extractModalTestHooks;

  await import(moduleUrl);

  assert.ok(
    globalThis.__extractModalTestHooks,
    "extract_modal.js should expose testable render helpers"
  );

  const { normalizeReferenceRows, renderReferencePanelHTML } =
    globalThis.__extractModalTestHooks;

  const model = normalizeReferenceRows({
    engine_used: "papermage",
    references_data: {
      references: [
        {
          id: "ref-3",
          ref_id: "ref-3",
          index: 3,
          page: 11,
          text: "Brennan, K. New frameworks for studying computational thinking.",
          title: "New frameworks for studying computational thinking",
          author: "Brennan",
          doi: "10.1145/example",
        },
        {
          id: "ref-8",
          ref_id: "ref-8",
          index: 8,
          page: 12,
          text: "Wing, J. Computational thinking.",
          title: "Computational thinking",
          author: "Wing",
        },
      ],
      citations: [
        {
          id: "cite-1",
          ref_id: "ref-3",
          page: 4,
          text: "artifact-based rubrics [3]",
        },
        {
          id: "cite-2",
          ref_id: "ref-3",
          page: 5,
          text: "classroom interventions [3]",
        },
        {
          id: "cite-3",
          ref_id: "ref-8",
          page: 6,
          text: "Computational thinking appears again [8]",
        },
      ],
      contexts: [
        {
          id: "citation-context-cite-1",
          ref_id: "ref-3",
          page: 4,
          text: "This is the entire paragraph explaining how artifact-based rubrics connect to the reference [3].",
        },
        {
          id: "citation-context-cite-3",
          ref_id: "ref-8",
          page: 6,
          text: "A full paragraph for the Wing reference that should be visible when its mention is expanded.",
        },
      ],
    },
  });

  const html = renderReferencePanelHTML(model, "", "ref-3");

  assert.match(html, /extract-ref-panel/);
  assert.match(html, /Refs: 2/);
  assert.match(html, /Citas: 3/);
  assert.match(html, /Contextos: 2/);
  assert.match(html, /#3/);
  assert.match(html, /p\. 12 \| menciones: 2/);
  assert.match(html, /New frameworks for studying computational thinking/);
  assert.match(html, /DOI: 10\.1145\/example/);
  assert.match(html, /artifact-based rubrics \[3\]/);
  assert.match(html, /Computational thinking appears again \[8\]/);
  assert.doesNotMatch(html, /This is the entire paragraph explaining/);
  assert.doesNotMatch(html, /Copiar referencia/);
  assert.doesNotMatch(html, /Ver JSON/);

  const expandedHtml = renderReferencePanelHTML(model, "", "ref-3", "ref-3:0");

  assert.match(expandedHtml, /aria-expanded="true"/);
  assert.match(expandedHtml, /This is the entire paragraph explaining/);

  const filteredHtml = renderReferencePanelHTML(model, "Wing", "");

  assert.match(filteredHtml, /#8/);
  assert.doesNotMatch(filteredHtml, /#3/);
});
