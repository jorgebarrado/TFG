from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
INLINE_CITATION_REGEX = re.compile(
    r"\[\s*(\d+(?:\s*[,;]\s*\d+|\s*[-\u2013\u2014]\s*\d+)*)\s*\]"
)


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _normalize_page_zero_based(raw_page: Any) -> Optional[int]:
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return None
    if page < 0:
        return None
    # Snippets suelen venir 1-based; layers ya vienen 0-based.
    if page > 0:
        return page - 1
    return page


def _normalize_box(raw_box: Any) -> Optional[List[float]]:
    if not isinstance(raw_box, (list, tuple)) or len(raw_box) < 4:
        return None

    x = _to_float(raw_box[0])
    y = _to_float(raw_box[1])
    w = _to_float(raw_box[2])
    h = _to_float(raw_box[3])
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0:
        return None

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0 - x, w))
    h = max(0.0, min(1.0 - y, h))
    if w <= 0 or h <= 0:
        return None
    return [x, y, w, h]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _tokenize(value: str) -> set[str]:
    text = _normalize_text(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text)
        if token not in {"http", "https", "www", "doi"}
    }


def _normalize_doi(value: str) -> str:
    candidate = str(value or "").strip()
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    return candidate.rstrip(").,;:]").strip().lower()


def _extract_doi(text: str) -> str:
    if not text:
        return ""
    url_match = DOI_URL_REGEX.search(text)
    if url_match:
        return _normalize_doi(url_match.group(1))
    match = DOI_REGEX.search(text)
    if match:
        return _normalize_doi(match.group(0))
    return ""


def _parse_citation_numbers(text: str) -> List[int]:
    if not text:
        return []
    numbers: set[int] = set()
    for match in INLINE_CITATION_REGEX.finditer(text):
        raw = match.group(1)
        parts = re.split(r"[,;]", raw)
        for part in parts:
            token = part.replace("\u2013", "-").replace("\u2014", "-").strip()
            if not token:
                continue
            if "-" in token:
                bounds = [segment.strip() for segment in token.split("-", 1)]
                if len(bounds) != 2:
                    continue
                try:
                    start = int(bounds[0])
                    end = int(bounds[1])
                except (TypeError, ValueError):
                    continue
                step = 1 if start <= end else -1
                span = min(abs(end - start) + 1, 50)
                for idx in range(span):
                    numbers.add(start + idx * step)
                continue
            try:
                numbers.add(int(token))
            except (TypeError, ValueError):
                continue
    return sorted(number for number in numbers if number > 0)


def _entry_index(entry: Dict[str, Any]) -> Optional[int]:
    raw_index = entry.get("index")
    if isinstance(raw_index, int) and raw_index > 0:
        return raw_index
    try:
        parsed = int(raw_index)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    return None


def _layer_items(layers: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    raw_items = layers.get(key)
    if not isinstance(raw_items, list):
        return []
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        if not isinstance(page, int):
            try:
                page = int(page)
            except (TypeError, ValueError):
                continue
        box = _normalize_box(item.get("box"))
        if page < 0 or box is None:
            continue
        out.append(
            {
                "id": str(item.get("id") or f"{key}-{idx}"),
                "text": str(item.get("text") or ""),
                "page": page,
                "box": box,
            }
        )
    return out


def _reference_match_score(reference_text: str, reference_index: int, reference_doi: str, candidate_text: str) -> float:
    score = 0.0
    cand_norm = _normalize_text(candidate_text)
    if not cand_norm:
        return score

    if reference_doi and reference_doi in cand_norm:
        score += 5.0

    if reference_index > 0:
        if re.search(rf"^\s*\[\s*{reference_index}\s*\]", cand_norm):
            score += 3.0
        elif re.search(rf"^\s*{reference_index}[\.\)]\s*", cand_norm):
            score += 2.5

    ref_tokens = _tokenize(reference_text)
    cand_tokens = _tokenize(candidate_text)
    if ref_tokens and cand_tokens:
        overlap = len(ref_tokens.intersection(cand_tokens))
        score += overlap / max(len(ref_tokens), 1)

    return score


def _box_center(box: Sequence[float]) -> Tuple[float, float]:
    return (float(box[0]) + float(box[2]) / 2.0, float(box[1]) + float(box[3]) / 2.0)


def _contains_box(container: Sequence[float], inner: Sequence[float]) -> bool:
    cx, cy = _box_center(inner)
    return (
        float(container[0]) <= cx <= float(container[0]) + float(container[2])
        and float(container[1]) <= cy <= float(container[1]) + float(container[3])
    )


def _overlap_ratio(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    ax0 = float(box_a[0])
    ay0 = float(box_a[1])
    ax1 = ax0 + float(box_a[2])
    ay1 = ay0 + float(box_a[3])
    bx0 = float(box_b[0])
    by0 = float(box_b[1])
    bx1 = bx0 + float(box_b[2])
    by1 = by0 + float(box_b[3])

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    area = max(float(box_b[2]) * float(box_b[3]), 1e-9)
    return inter / area


def _pick_best_text_box(snippet_text: str, page_hint: Optional[int], rows: List[Dict[str, Any]], paragraphs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    normalized_snippet = _normalize_text(snippet_text)
    if not normalized_snippet:
        return None

    tokens = _tokenize(normalized_snippet)
    candidate_pool = [item for item in rows if page_hint is None or item["page"] == page_hint]
    if not candidate_pool:
        candidate_pool = [item for item in paragraphs if page_hint is None or item["page"] == page_hint]
    if not candidate_pool:
        return None

    best_item: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for item in candidate_pool:
        item_text = _normalize_text(item.get("text", ""))
        if not item_text:
            continue
        score = 0.0
        if normalized_snippet in item_text:
            score += 2.5
        elif item_text in normalized_snippet:
            score += 1.5

        item_tokens = _tokenize(item_text)
        if tokens and item_tokens:
            overlap = len(tokens.intersection(item_tokens))
            score += overlap / max(len(tokens), 1)

        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_score >= 0.15 else None


def build_references_data(
    *,
    references: Sequence[Dict[str, Any]],
    snippets: Sequence[Dict[str, Any]],
    layers: Dict[str, Any],
    references_numbered: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    bibliography_items = _layer_items(layers, "bibliographies")
    row_items = _layer_items(layers, "rows")
    paragraph_items = _layer_items(layers, "paragraphs")

    reference_entries: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    contexts: List[Dict[str, Any]] = []

    references_by_index: Dict[int, str] = {}
    references_by_doi: Dict[str, str] = {}
    used_bibliography_ids: set[str] = set()

    for fallback_idx, ref in enumerate(references, start=1):
        if not isinstance(ref, dict):
            continue
        idx = _entry_index(ref)
        if idx is not None:
            ref_id = f"ref-{idx}"
            references_by_index[idx] = ref_id
        else:
            ref_id = f"ref-unlabeled-{fallback_idx}"
        doi_value = _normalize_doi(str(ref.get("doi") or ""))
        if doi_value:
            references_by_doi[doi_value] = ref_id

        raw_text = str(ref.get("raw") or ref.get("text") or "")
        best_candidate: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for candidate in bibliography_items:
            if candidate["id"] in used_bibliography_ids:
                continue
            score = _reference_match_score(
                raw_text,
                idx or 0,
                doi_value,
                str(candidate.get("text") or ""),
            )
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate and best_score >= 0.35:
            used_bibliography_ids.add(best_candidate["id"])
            page = best_candidate["page"]
            box = best_candidate["box"]
            text = str(best_candidate.get("text") or raw_text)
        else:
            page = None
            box = None
            text = raw_text

        reference_entries.append(
            {
                "id": f"reference-entry-{ref_id}",
                "ref_id": ref_id,
                "index": idx,
                "text": text,
                "page": page,
                "box": box,
                "doi": doi_value or None,
            }
        )

    contexts_seen: set[Tuple[str, int, str]] = set()

    for snippet_idx, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        snippet_text = str(snippet.get("snippet") or snippet.get("text") or "")
        if not snippet_text:
            continue

        ref_ids: List[str] = []
        doi_in_snippet = _extract_doi(snippet_text)
        if doi_in_snippet and doi_in_snippet in references_by_doi:
            ref_ids.append(references_by_doi[doi_in_snippet])

        if references_numbered:
            for number in _parse_citation_numbers(snippet_text):
                ref_id = references_by_index.get(number)
                if ref_id:
                    ref_ids.append(ref_id)

        # Dedupe preservando orden.
        seen_ref_ids: set[str] = set()
        dedup_ref_ids: List[str] = []
        for ref_id in ref_ids:
            if ref_id in seen_ref_ids:
                continue
            seen_ref_ids.add(ref_id)
            dedup_ref_ids.append(ref_id)
        if not dedup_ref_ids:
            continue

        page_hint = _normalize_page_zero_based(snippet.get("page"))
        mention_anchor = _pick_best_text_box(
            snippet_text,
            page_hint,
            row_items,
            paragraph_items,
        )
        mention_page = (
            mention_anchor["page"]
            if mention_anchor is not None
            else page_hint
        )
        mention_box = mention_anchor["box"] if mention_anchor is not None else None

        for mention_pos, ref_id in enumerate(dedup_ref_ids, start=1):
            mention_id = f"citation-mention-{snippet_idx}-{mention_pos}-{ref_id}"
            mention_item = {
                "id": mention_id,
                "ref_id": ref_id,
                "text": snippet_text,
                "page": mention_page,
                "box": mention_box,
            }
            citations.append(mention_item)

            if mention_page is None or mention_box is None:
                continue
            page_paragraphs = [item for item in paragraph_items if item["page"] == mention_page]
            if not page_paragraphs:
                continue

            best_context = None
            best_context_score = 0.0
            snippet_tokens = _tokenize(snippet_text)
            for paragraph in page_paragraphs:
                score = 0.0
                paragraph_box = paragraph["box"]
                if _contains_box(paragraph_box, mention_box):
                    score += 3.0
                score += _overlap_ratio(paragraph_box, mention_box) * 2.0

                paragraph_tokens = _tokenize(str(paragraph.get("text") or ""))
                if snippet_tokens and paragraph_tokens:
                    overlap = len(snippet_tokens.intersection(paragraph_tokens))
                    score += overlap / max(len(snippet_tokens), 1)
                if score > best_context_score:
                    best_context_score = score
                    best_context = paragraph

            if best_context is None or best_context_score < 0.2:
                continue

            rounded_box = ",".join(f"{value:.4f}" for value in best_context["box"])
            seen_key = (ref_id, mention_page, rounded_box)
            if seen_key in contexts_seen:
                continue
            contexts_seen.add(seen_key)

            contexts.append(
                {
                    "id": f"citation-context-{mention_id}",
                    "ref_id": ref_id,
                    "text": str(best_context.get("text") or snippet_text),
                    "page": best_context["page"],
                    "box": best_context["box"],
                }
            )

    # Limpieza final: solo entradas con página/caja válidas para overlays.
    def _clean_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        for item in items:
            page = item.get("page")
            box = _normalize_box(item.get("box"))
            next_item = dict(item)
            next_item["page"] = page if isinstance(page, int) and page >= 0 else None
            next_item["box"] = box
            cleaned.append(next_item)
        return cleaned

    reference_entries = _clean_items(reference_entries)
    citations = _clean_items(citations)
    contexts = _clean_items(contexts)

    return {
        "references": reference_entries,
        "citations": citations,
        "contexts": contexts,
    }
