from __future__ import annotations

import json
import random
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import IncorrectCitation, UserProfile
from ..services.evidence import normalize_evidence_items
from ..services.dblp_client import DBLPClientError, get_author_papers
from ..services.semantic_scholar_client import (
    SemanticScholarError,
    get_citation_counts_for_dois,
)


def _build_original_metadata(paper: dict) -> dict:
    return {
        "title": paper.get("title"),
        "doi": paper.get("doi"),
        "year": paper.get("year"),
        "type": paper.get("type"),
        "authors": paper.get("authors"),
        "url": paper.get("url"),
        "dblp_key": paper.get("dblp_key"),
        "source": "dblp",
    }


def _build_citing_metadata(paper: dict) -> dict:
    return {
        "title": paper.get("title"),
        "doi": paper.get("doi"),
        "year": paper.get("year"),
        "authors": paper.get("authors"),
        "url": paper.get("url"),
        "source": "semantic_scholar",
    }


def _resolve_dblp_url(request) -> str:
    """Obtiene la URL de DBLP del parámetro GET o del perfil del usuario autenticado."""
    url = request.GET.get("dblp_url", "").strip()
    if not url and request.user.is_authenticated:
        profile = UserProfile.objects.filter(user=request.user).first()
        if profile:
            url = profile.dblp_url or ""
    return url


def _saved_dblp_url(request) -> str:
    if not request.user.is_authenticated:
        return ""
    profile = UserProfile.objects.filter(user=request.user).first()
    return (profile.dblp_url or "") if profile else ""


def _assign_paper_ids(papers: list[dict]) -> None:
    for idx, paper in enumerate(papers):
        paper["paper_id"] = idx


def _filter_papers_with_citers(papers: list[dict]) -> list[dict]:
    citation_counts = get_citation_counts_for_dois(
        [paper.get("doi") for paper in papers if paper.get("doi")]
    )
    papers_with_citers = []
    for paper in papers:
        doi = paper.get("doi")
        paper["citation_count"] = (
            citation_counts.get(str(doi).strip(), 0) if doi else 0
        )
        if paper["citation_count"] > 0:
            papers_with_citers.append(paper)
    return papers_with_citers


def citation_review_papers(request):
    # Flujo legacy: la revisión DBLP ya no es una pantalla oficial. DBLP actua
    # como selector y el resultado unificado vive en doi_search_view.
    query = request.GET.urlencode()
    target = reverse("dblp_articles")
    if query:
        target = f"{target}?{query}"
    return redirect(target)


def citation_review_citers(request, paper_id: int):
    dblp_url = _resolve_dblp_url(request)

    if not dblp_url:
        messages.warning(request, "Introduce tu URL de DBLP para continuar.")
        return redirect("dblp_articles")

    try:
        all_papers = get_author_papers(dblp_url)
    except DBLPClientError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("dblp_articles") + "?" + urlencode({"dblp_url": dblp_url}))

    if paper_id < 0 or paper_id >= len(all_papers):
        return redirect(reverse("dblp_articles") + "?" + urlencode({"dblp_url": dblp_url}))

    paper = all_papers[paper_id]
    paper["paper_id"] = paper_id
    if paper.get("doi"):
        return redirect(reverse("doi_search") + "?" + urlencode({"doi": paper["doi"]}))
    messages.warning(request, "Este articulo no tiene DOI, así que no se puede buscar citadores.")
    return redirect(reverse("dblp_articles") + "?" + urlencode({"dblp_url": dblp_url}))


def citation_review_random(request):
    """Redirige a los citantes de un artículo aleatorio con DOI."""
    dblp_url = _resolve_dblp_url(request)

    if not dblp_url:
        messages.warning(request, "Introduce tu URL de DBLP para continuar.")
        return redirect("dblp_articles")

    try:
        all_papers = get_author_papers(dblp_url)
    except DBLPClientError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("dblp_articles") + "?" + urlencode({"dblp_url": dblp_url}))

    _assign_paper_ids(all_papers)
    try:
        papers_with_citers = _filter_papers_with_citers(all_papers)
    except SemanticScholarError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("dblp_articles") + "?" + urlencode({"dblp_url": dblp_url}))
    if not papers_with_citers:
        messages.warning(request, "No hay articulos con citantes en este perfil DBLP.")
        return redirect(reverse("dblp_articles") + "?" + urlencode({"dblp_url": dblp_url}))

    paper = random.choice(papers_with_citers)
    return redirect(reverse("doi_search") + "?" + urlencode({"doi": paper["doi"]}))


@require_POST
@login_required
def citation_review_create_report(request):
    original_doi = (request.POST.get("original_doi") or "").strip()
    citing_doi = (request.POST.get("citing_doi") or "").strip()

    def _parse_json(name: str) -> dict:
        raw = request.POST.get(name) or ""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    metadata_original = _parse_json("original_metadata_json")
    metadata_incorrect = _parse_json("citing_metadata_json")
    evidence_items = normalize_evidence_items(
        request.POST.get("citation_contexts_json")
        or request.POST.get("citing_paragraphs_json"),
        default_source="semantic_scholar",
        default_article="citing",
        default_kind="citation_context",
        default_doi=citing_doi,
    )

    if not original_doi and not citing_doi:
        messages.error(request, "No se pudo crear el reporte sin DOIs.")
        return redirect("doi_search")

    citation = IncorrectCitation(
        author=request.user,
        doi_original=original_doi,
        doi_incorrect=citing_doi,
        incorrect_reason="Pendiente de completar",
        citation_type="not said",
        publication_area="OTH",
        metadata_original=metadata_original,
        metadata_incorrect=metadata_incorrect,
        citation_contexts=evidence_items,
    )
    citation.save()

    messages.success(request, "Reporte creado. Completa la explicación en el detalle.")
    return redirect("citation_detail", pk=citation.pk)
