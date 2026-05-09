# Report List Pagination Design

## Goal

Expose all reports in the public report list by using a single, visible server-side pagination flow.

## Root Cause

- The view already paginates `IncorrectCitation` with Django `Paginator` at 25 items per page.
- The template does not render any server pagination controls, so users cannot navigate past page 1.
- The page also initializes DataTables with its own client-side pagination at 10 rows, which creates a second paginator and hides the real source of truth.

## Chosen Approach

- Keep Django server pagination as the only pagination mechanism for `citation_list`.
- Remove DataTables and the AJAX partial-refresh logic from this page.
- Add visible pagination controls below the table.
- Preserve active filters (`q`, `area`, `ctype`, `year`) in pagination links.
- Replace JS-only filter actions with standard GET form submission so filtering still works without AJAX.

## Testing

- Add a template-level regression test that requires a visible link to page 2 when more than one server page exists.
- Add a regression test that verifies pagination links preserve active filters.

## Out of Scope

- Changing page size.
- Reworking the visual style of the report table beyond the required filter/pagination controls.
