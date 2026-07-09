# Extract Modal Reader-Style References Design

## Goal

Improve how extracted citations and references are shown in the extraction modal. The result should visually match the reader's right column, especially the `Referencias` tab, instead of showing isolated plain cards for each detected citation.

## Approved Direction

Use option B: a reader-like references list inside the modal.

The modal should render extraction results as a compact references panel:

- Header with total references.
- Metric pills for references, citation mentions, and contexts.
- Status message for the extraction result.
- Search input to filter references.
- One row per reference, using the reader visual hierarchy: index, page, mention count, reference snippet, title/author/DOI metadata, and expandable/clickable mentions.

## Data Flow

The modal should prefer `data.references_data` when the backend returns it:

- `references_data.references` drives the reference rows.
- `references_data.citations` drives mention counts and mention previews.
- `references_data.contexts` can contribute context counts and future detail.

If `references_data` is missing or empty, the modal must fall back to the existing `data.references` and `data.results` behavior so AI engines or older responses still show useful output.

## Components

Changes stay scoped to:

- `tfg_project/citations/static/js/extract_modal.js`
- `tfg_project/citations/static/css/custom.css`
- Existing `extract_modal.html` IDs remain stable unless a small wrapper class is needed.

No backend API changes are required.

## Interactions

The modal should support:

- Text search across reference text, title, author, DOI, and mention text.
- Selecting a reference row to expand associated mentions.
- Copy actions for reference text and mention text.
- Existing debug download and reader preview buttons remain unchanged.

The previous "Ver JSON" debug-style action can remain as a secondary action where a raw payload exists.

## Empty And Error States

The UI should show clear inline states for:

- No references detected.
- References detected but no linked citations.
- Search with no matches.
- Extraction failure, continuing to use the existing alert area.

## Styling

Use CSS classes local to the extraction modal, but mirror the reader's visual vocabulary:

- Pill metrics similar to `.reader-pill`.
- Status panel similar to `.reader-panel-status`.
- Reference rows similar to `.reader-ref-row`.
- Snippet blocks similar to `.reader-ref-snippet`.
- Mention chips/rows similar to `.reader-ref-mention`.

Keep the modal compact and readable inside the existing Bootstrap modal. Avoid importing reader CSS directly to prevent coupling the Django modal to the standalone reader bundle.

## Testing

Add focused JavaScript-level coverage if the project already has a browser/JS test harness available. If not, verify manually with representative payloads by exercising:

- `references_data` response with references, citations, and contexts.
- Fallback response using only `results`.
- Empty response.
- Search filtering and row expansion.

Run existing Django checks/tests that are practical for this scoped frontend change.
