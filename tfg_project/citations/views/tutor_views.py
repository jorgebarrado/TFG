from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import IncorrectCitation, UserProfile
from ..services.dblp_client import DBLPClientError, get_author_papers
from ..services.semantic_scholar_client import (
    SemanticScholarError,
    get_citing_papers_for_doi_paginated,
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


@login_required
def citation_review_papers(request):
    profile = get_object_or_404(UserProfile, user=request.user)
    dblp_url = profile.dblp_url

    if not dblp_url:
        return render(
            request,
            "citations/tutor_papers.html",
            {
                "papers": None,
                "dblp_url": None,
            },
        )

    try:
        all_papers = get_author_papers(dblp_url)
    except DBLPClientError as exc:
        messages.error(request, str(exc))
        all_papers = []

    for idx, paper in enumerate(all_papers):
        paper["paper_id"] = idx

    paginator = Paginator(all_papers, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    context = {
        "papers": page,
        "dblp_url": dblp_url,
    }
    return render(request, "citations/tutor_papers.html", context)


@login_required
def citation_review_citers(request, paper_id: int):
    profile = get_object_or_404(UserProfile, user=request.user)
    dblp_url = profile.dblp_url
    if not dblp_url:
        messages.warning(request, "Configura tu URL de DBLP antes de usar la revision de citas.")
        return redirect("citation_review_papers")

    try:
        all_papers = get_author_papers(dblp_url)
    except DBLPClientError as exc:
        messages.error(request, str(exc))
        return redirect("citation_review_papers")

    if paper_id < 0 or paper_id >= len(all_papers):
        return redirect("citation_review_papers")

    paper = all_papers[paper_id]
    paper["paper_id"] = paper_id

    citing_papers = []
    total = 0
    error_message = None
    limit = 10
    offset = 0
    offset_raw = request.GET.get("offset")
    if offset_raw and offset_raw.isdigit():
        offset = int(offset_raw)

    if paper.get("doi"):
        try:
            citing_papers, total = get_citing_papers_for_doi_paginated(
                paper["doi"], limit=limit, offset=offset
            )
        except (ValueError, SemanticScholarError) as exc:
            error_message = str(exc)
    else:
        error_message = "Este articulo no tiene DOI, asi que no se puede revisar."

    registered_map = {}
    if paper.get("doi"):
        citing_dois = [c.get("doi") for c in citing_papers if c.get("doi")]
        if citing_dois:
            registered = IncorrectCitation.objects.filter(
                doi_original=paper["doi"],
                doi_incorrect__in=citing_dois,
            ).values("doi_incorrect", "id")
            registered_map = {row["doi_incorrect"]: row["id"] for row in registered}

    for citing in citing_papers:
        citing_doi = citing.get("doi")
        if citing_doi and citing_doi in registered_map:
            citing["is_reported"] = True
            citing["report_id"] = registered_map[citing_doi]
        else:
            citing["is_reported"] = False
            citing["report_id"] = None
        citing["metadata_json"] = json.dumps(
            _build_citing_metadata(citing), ensure_ascii=True
        )

    paper["metadata_json"] = json.dumps(_build_original_metadata(paper), ensure_ascii=True)

    next_offset = None
    if total and (offset + limit) < total:
        next_offset = offset + limit

    range_start = offset + 1 if citing_papers else 0
    range_end = offset + len(citing_papers)

    context = {
        "paper": paper,
        "citing_papers": citing_papers,
        "error_message": error_message,
        "offset": offset,
        "limit": limit,
        "total": total,
        "next_offset": next_offset,
        "range_start": range_start,
        "range_end": range_end,
    }
    return render(request, "citations/tutor_citers.html", context)


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

    if not original_doi and not citing_doi:
        messages.error(request, "No se pudo crear el reporte sin DOIs.")
        return redirect("citation_review_papers")

    citation = IncorrectCitation(
        author=request.user,
        doi_original=original_doi,
        doi_incorrect=citing_doi,
        incorrect_reason="Pendiente de completar",
        citation_type="not said",
        publication_area="OTH",
        metadata_original=metadata_original,
        metadata_incorrect=metadata_incorrect,
    )
    citation.save()

    messages.success(request, "Reporte creado. Completa la explicacion en el detalle.")
    return redirect("citation_detail", pk=citation.pk)
