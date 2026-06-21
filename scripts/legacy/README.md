Scripts archived because they are one-off local diagnostics, not part of the
current Docker-based development flow.

- `test_citation_contexts.py` uses a hardcoded PDF path under a local Downloads
  folder.
- `test_papermage_raw.py` uses a hardcoded PDF path under a local Downloads
  folder.

Keep these only as historical debugging references. Prefer parameterized
scripts in `scripts/` for active maintenance.
