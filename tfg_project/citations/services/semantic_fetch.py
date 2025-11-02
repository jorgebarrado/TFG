import requests

S2_BASE = "https://api.semanticscholar.org/graph/v1"
CR_BASE = "https://api.crossref.org"


def _safe_get(url, params=None, timeout=12):
    headers = {"User-Agent": "CiteCheck/1.0 (mailto:you@example.com)"}
    try:
        r = requests.get(url, params=params or {}, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def get_s2_paperid_and_count(doi: str) -> tuple[str | None, int]:
    """Devuelve (paperId, citationCount) o (None, 0)."""
    url = f"{S2_BASE}/paper/DOI:{doi}"
    data = _safe_get(url, params={"fields": "paperId,citationCount"})
    if not data:
        return None, 0
    return data.get("paperId"), int(data.get("citationCount") or 0)


def get_s2_citations(doi: str, limit: int = 100) -> list[dict]:
    """Usa el endpoint específico /citations con paginado."""
    paper_id, count = get_s2_paperid_and_count(doi)
    if not paper_id or count == 0:
        return []

    out: list[dict] = []
    offset = 0
    while True:
        url = f"{S2_BASE}/paper/{paper_id}/citations"
        params = {
            "fields": "citingPaper.title,citingPaper.authors,"
            "citingPaper.year,citingPaper.externalIds,citingPaper.url",
            "limit": min(limit, 100),
            "offset": offset,
        }
        data = _safe_get(url, params=params)
        if not data or not data.get("data"):
            break

        for row in data["data"]:
            cp = row.get("citingPaper") or {}
            ext = cp.get("externalIds") or {}
            out.append(
                {
                    "title": cp.get("title"),
                    "authors": ", ".join(
                        a.get("name", "") for a in (cp.get("authors") or [])
                    ),
                    "year": cp.get("year"),
                    "doi": ext.get("DOI"),
                    "url": cp.get("url"),
                }
            )
        offset += params["limit"]
        if offset >= count or offset >= 1000:  # cota de seguridad
            break
    return out


def get_crossref_citations(doi: str, rows: int = 100) -> list[dict]:
    """Fallback:
    Crossref devuelve works que incluyen reference.doi = DOI dado
    (citan al artículo)."""
    url = f"{CR_BASE}/works"
    # Nota: rows máx ~1000; aquí 100 es razonable para UI
    params = {
        "filter": f"reference.doi:{doi}",
        "rows": rows,
        "select": "title,author,issued,DOI,URL",
    }
    data = _safe_get(url, params=params)
    items = (data or {}).get("message", {}).get("items", [])
    out: list[dict] = []
    for it in items:
        title = (it.get("title") or [""])[0]
        authors = ", ".join(
            [
                f"{a.get('family', '')}" if isinstance(a, dict) else ""
                for a in (it.get("author") or [])
            ]
        )
        year = None
        try:
            year = it.get("issued", {}).get("date-parts", [[None]])[0][0]
        except Exception:
            pass
        out.append(
            {
                "title": title,
                "authors": authors,
                "year": year,
                "doi": it.get("DOI"),
                "url": it.get("URL"),
                "source": "crossref",
            }
        )
    return out


def get_citations_with_fallback(doi: str) -> tuple[int, list[dict], str]:
    """
    Devuelve: (citation_count_estimado, lista_citas, fuente_usada)
    fuente_usada ∈ {"s2","crossref","none"}
    """
    s2_list = get_s2_citations(doi)
    if s2_list:
        return len(s2_list), s2_list, "s2"

    # Si S2 no devuelve nada pero el contador era >0, probamos Crossref:
    cr_list = get_crossref_citations(doi)
    if cr_list:
        return len(cr_list), cr_list, "crossref"

    # Nada
    _, count = get_s2_paperid_and_count(doi)  # para reportar el count si existe
    return count, [], "none"
