# Extract Modal Reader References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render extracted citations in the extraction modal as a reader-like references panel.

**Architecture:** Keep the backend response unchanged. Add pure normalization/render helpers to `extract_modal.js`, use `references_data` first, and keep `results` as fallback. Add scoped CSS in `custom.css` that mirrors the reader's reference rows without importing reader CSS.

**Tech Stack:** Django static JavaScript, Bootstrap modal, Node built-in test runner for pure helper coverage, existing Django checks.

---

### Task 1: Test Reader-Like Render Helpers

**Files:**
- Create: `tfg_project/citations/static/js/extract_modal.test.mjs`
- Modify later: `tfg_project/citations/static/js/extract_modal.js`

- [ ] **Step 1: Write the failing test**

Create a Node test that loads exported helper functions from `extract_modal.js` and verifies that `references_data` produces metric pills, reference rows, mention rows, and search filtering.

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tfg_project/citations/static/js/extract_modal.test.mjs`

Expected: FAIL because `__extractModalTestHooks` is not exported yet.

### Task 2: Implement Pure Modal Rendering Helpers

**Files:**
- Modify: `tfg_project/citations/static/js/extract_modal.js`
- Test: `tfg_project/citations/static/js/extract_modal.test.mjs`

- [ ] **Step 1: Add helpers**

Add helpers for:

- `normalizeReferenceRows(data)`
- `getReferencePanelNotice(model)`
- `renderReferencePanelHTML(model, query, selectedRefId)`

They must prefer `data.references_data`, fall back to `data.references` and `data.results`, and expose hooks through `window.__extractModalTestHooks` in browser and `globalThis.__extractModalTestHooks` in Node.

- [ ] **Step 2: Run test to verify it passes**

Run: `node --test tfg_project/citations/static/js/extract_modal.test.mjs`

Expected: PASS.

### Task 3: Wire Modal Interaction

**Files:**
- Modify: `tfg_project/citations/static/js/extract_modal.js`
- Test: `tfg_project/citations/static/js/extract_modal.test.mjs`

- [ ] **Step 1: Replace old card render**

Update `renderResults(data)` to render the reader-like panel into `#extract-results` using the pure helpers.

- [ ] **Step 2: Add delegated actions**

Update `wireCardActions()` so it binds once and supports:

- Filtering via `[data-action="filter-references"]`.
- Selecting rows via `[data-action="select-reference"]`.
- Copying references and mentions.
- Viewing JSON for raw payloads.

- [ ] **Step 3: Run tests**

Run: `node --test tfg_project/citations/static/js/extract_modal.test.mjs`

Expected: PASS.

### Task 4: Add Scoped CSS

**Files:**
- Modify: `tfg_project/citations/static/css/custom.css`

- [ ] **Step 1: Add classes**

Add `.extract-ref-*` classes for metrics, status, search, row, snippet, footer, mentions, actions, and empty states. Match reader spacing and color hierarchy, scoped to the extraction modal.

- [ ] **Step 2: Check CSS does not affect reader**

Confirm class names are not `.reader-*` and do not override Bootstrap globally.

### Task 5: Verify

**Files:**
- Test: `tfg_project/citations/static/js/extract_modal.test.mjs`

- [ ] **Step 1: Run JS test**

Run: `node --test tfg_project/citations/static/js/extract_modal.test.mjs`

Expected: PASS.

- [ ] **Step 2: Run Django check**

Run: `python tfg_project/manage.py check`

Expected: no system check issues.

- [ ] **Step 3: Review diff**

Run: `git diff -- tfg_project/citations/static/js/extract_modal.js tfg_project/citations/static/css/custom.css tfg_project/citations/static/js/extract_modal.test.mjs`

Expected: only modal render/test/style changes.
