# Report List Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every public report reachable from the report list with one server-side pagination system.

**Architecture:** Keep `citations.views.page_views.citation_list` as the single source of truth for pagination and filtering. Render standard GET-based filter controls and page navigation in `citation_list.html`, removing the client-side DataTables/AJAX layer that currently conflicts with the server paginator.

**Tech Stack:** Django views, Django templates, Django test suite

---

### Task 1: Lock the missing-pagination behavior with tests

**Files:**
- Modify: `tfg_project/citations/tests.py`
- Test: `tfg_project/citations/tests.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_citation_list_shows_server_pagination_controls(self):
    ...
    self.assertContains(response, "?page=2")

def test_citation_list_preserves_filters_in_pagination_links(self):
    ...
    self.assertContains(response, "?area=CIS&amp;page=2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv311\Scripts\python.exe tfg_project/manage.py test citations.tests.PageLoadTests`
Expected: FAIL because the rendered template does not output pagination controls.

### Task 2: Render one paginator and plain GET filters

**Files:**
- Modify: `tfg_project/citations/views/page_views.py`
- Modify: `tfg_project/citations/templates/citations/citation_list.html`

- [ ] **Step 1: Prepare pagination query data in the view**

```python
query_params = request.GET.copy()
query_params.pop("page", None)
pagination_query = query_params.urlencode()
```

- [ ] **Step 2: Replace JS-only filter interactions with plain GET controls**

```html
<button type="submit" class="btn btn-dark w-100">Aplicar filtros</button>
<a href="{% url 'citation_list' %}" class="btn btn-outline-secondary w-100">Borrar filtros</a>
```

- [ ] **Step 3: Render server pagination controls**

```html
{% if citations.has_other_pages %}
  <a href="?{% if pagination_query %}{{ pagination_query }}&amp;{% endif %}page={{ citations.next_page_number }}">
    Siguiente
  </a>
{% endif %}
```

- [ ] **Step 4: Remove DataTables/AJAX code from this page**

```html
{% block scripts %}
  <script>
    // keep DOI modal behavior only
  </script>
{% endblock %}
```

### Task 3: Verify and finish

**Files:**
- Modify: `tfg_project/citations/tests.py`
- Modify: `tfg_project/citations/views/page_views.py`
- Modify: `tfg_project/citations/templates/citations/citation_list.html`

- [ ] **Step 1: Run the focused tests**

Run: `.\.venv311\Scripts\python.exe tfg_project/manage.py test citations.tests.PageLoadTests`
Expected: PASS

- [ ] **Step 2: Run a broader regression slice for citation pages**

Run: `.\.venv311\Scripts\python.exe tfg_project/manage.py test citations.tests`
Expected: PASS or unrelated pre-existing failures only
