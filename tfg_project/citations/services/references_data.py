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


def _normalize_mention_text(text: str) -> str:
    normalized = _normalize_text(text or "")
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _quantize_box(box: Any, decimals: int = 3) -> Optional[Tuple[float, float, float, float]]:
    normalized_box = _normalize_box(box)
    if normalized_box is None:
        return None
    return tuple(round(float(value), decimals) for value in normalized_box)


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


def is_after_bibliography(
    page: Optional[int],
    y: Optional[float],
    bibliography_anchor: Optional[Tuple[int, float]],
) -> bool:
    if bibliography_anchor is None:
        return False
    if not isinstance(page, int) or page < 0:
        return False

    anchor_page, anchor_y = bibliography_anchor
    if page > anchor_page:
        return True
    if page < anchor_page:
        return False
    if y is None:
        return True
    return float(y) >= float(anchor_y)


def is_inside_bibliography(
    box: Any,
    bibliography_items: Sequence[Dict[str, Any]],
) -> bool:
    if not bibliography_items:
        return False

    candidate_page: Optional[int] = None
    candidate_box: Optional[List[float]] = None
    if isinstance(box, dict):
        raw_page = box.get("page")
        if isinstance(raw_page, int) and raw_page >= 0:
            candidate_page = raw_page
        candidate_box = _normalize_box(box.get("box"))
    else:
        candidate_box = _normalize_box(box)

    if candidate_box is None:
        return False

    for bibliography_item in bibliography_items:
        bibliography_page = bibliography_item.get("page")
        bibliography_box = bibliography_item.get("box")
        if not isinstance(bibliography_page, int) or bibliography_page < 0:
            continue
        if candidate_page is not None and bibliography_page != candidate_page:
            continue
        if not isinstance(bibliography_box, (list, tuple)) or len(bibliography_box) < 4:
            continue
        if _contains_box(bibliography_box, candidate_box):
            return True
        if _overlap_ratio(bibliography_box, candidate_box) >= 0.6:
            return True
    return False


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


def _box_area(box: Sequence[float]) -> float:
    return max(float(box[2]), 0.0) * max(float(box[3]), 0.0)


def _box_iou(box_a: Sequence[float], box_b: Sequence[float]) -> float:
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
    if inter <= 0:
        return 0.0
    union = _box_area(box_a) + _box_area(box_b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def _union_boxes(boxes: Sequence[Sequence[float]]) -> Optional[List[float]]:
    if not boxes:
        return None
    x0 = min(float(box[0]) for box in boxes)
    y0 = min(float(box[1]) for box in boxes)
    x1 = max(float(box[0]) + float(box[2]) for box in boxes)
    y1 = max(float(box[1]) + float(box[3]) for box in boxes)
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    if width <= 0 or height <= 0:
        return None
    return [x0, y0, width, height]


def _normalize_citation_marker(value: str) -> str:
    if not value:
        return ""
    compact = re.sub(r"\s+", "", str(value or "")).strip().lower()
    return compact.replace("\u2013", "-").replace("\u2014", "-")


def _candidate_pages(
    page_hint: Optional[int],
    available_pages: Sequence[int],
) -> List[int]:
    known_pages = sorted(
        {
            int(page)
            for page in available_pages
            if isinstance(page, int) and page >= 0
        }
    )
    if page_hint is None:
        return known_pages

    ordered: List[int] = []
    for page in (page_hint, page_hint - 1, page_hint + 1):
        if page < 0:
            continue
        if page in known_pages and page not in ordered:
            ordered.append(page)
    if ordered:
        return ordered
    return known_pages


def _find_citation_marker_box(
    snippet_text: str,
    page_hint: Optional[int],
    tokens: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    marker_variants = {
        _normalize_citation_marker(match.group(0))
        for match in INLINE_CITATION_REGEX.finditer(snippet_text or "")
    }
    marker_variants = {value for value in marker_variants if value}
    if not marker_variants:
        return None

    tokens_by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for token in tokens:
        page = token.get("page")
        if not isinstance(page, int):
            continue
        token_text = _normalize_citation_marker(str(token.get("text") or ""))
        if not token_text:
            continue
        tokens_by_page[page].append(token)

    page_candidates = _candidate_pages(page_hint, list(tokens_by_page.keys()))
    if not page_candidates:
        return None

    best: Optional[Dict[str, Any]] = None
    best_rank: Optional[Tuple[int, float]] = None
    max_window = 8

    for page_priority, page in enumerate(page_candidates):
        page_tokens = tokens_by_page.get(page) or []
        if not page_tokens:
            continue
        ordered_tokens = sorted(
            page_tokens, key=lambda item: (float(item["box"][1]), float(item["box"][0]))
        )
        for marker in marker_variants:
            marker_length = len(marker)
            for start in range(len(ordered_tokens)):
                combined = ""
                candidate_boxes: List[Sequence[float]] = []
                previous_box: Optional[Sequence[float]] = None
                for offset in range(max_window):
                    token_index = start + offset
                    if token_index >= len(ordered_tokens):
                        break
                    token = ordered_tokens[token_index]
                    token_piece = _normalize_citation_marker(str(token.get("text") or ""))
                    if not token_piece:
                        continue
                    current_box = token["box"]
                    if previous_box is not None:
                        # Avoid mixing tokens from different lines.
                        if abs(float(current_box[1]) - float(previous_box[1])) > 0.02:
                            break
                    previous_box = current_box
                    combined += token_piece
                    candidate_boxes.append(current_box)
                    if len(combined) > marker_length + 2:
                        break
                    if combined == marker:
                        merged_box = _union_boxes(candidate_boxes)
                        if not merged_box:
                            break
                        area = _box_area(merged_box)
                        rank = (page_priority, area)
                        if best_rank is None or rank < best_rank:
                            best_rank = rank
                            best = {
                                "id": f"token-marker-{page}-{start}",
                                "text": marker,
                                "page": page,
                                "box": merged_box,
                            }
                        break

    return best


def _pick_best_text_box(
    snippet_text: str,
    page_hint: Optional[int],
    tokens: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    marker_anchor = _find_citation_marker_box(snippet_text, page_hint, tokens)
    if marker_anchor is not None:
        return marker_anchor

    normalized_snippet = _normalize_text(snippet_text)
    if not normalized_snippet:
        return None

    snippet_tokens = _tokenize(normalized_snippet)
    available_pages = [
        item.get("page")
        for item in rows + paragraphs
        if isinstance(item.get("page"), int)
    ]
    page_candidates = _candidate_pages(page_hint, available_pages)
    if page_hint is None and not page_candidates:
        page_candidates = [None]

    def _best_item_in_pool(pool: Sequence[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], float]:
        best_item: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for item in pool:
            item_text = _normalize_text(item.get("text", ""))
            if not item_text:
                continue
            score = 0.0
            if normalized_snippet in item_text:
                score += 2.5
            elif item_text in normalized_snippet:
                score += 1.5

            item_tokens = _tokenize(item_text)
            if snippet_tokens and item_tokens:
                overlap = len(snippet_tokens.intersection(item_tokens))
                score += overlap / max(len(snippet_tokens), 1)

            if score > best_score:
                best_score = score
                best_item = item
        return best_item, best_score

    best_rank: Optional[Tuple[int, int, float]] = None
    best_match: Optional[Dict[str, Any]] = None
    pool_specs = [("rows", rows), ("paragraphs", paragraphs)]

    for page_priority, candidate_page in enumerate(page_candidates):
        for pool_priority, (_, source_pool) in enumerate(pool_specs):
            if candidate_page is None:
                candidate_pool = list(source_pool)
            else:
                candidate_pool = [
                    item for item in source_pool if item.get("page") == candidate_page
                ]
            if not candidate_pool:
                continue
            match_item, match_score = _best_item_in_pool(candidate_pool)
            if match_item is None or match_score < 0.15:
                continue
            rank = (page_priority, pool_priority, -match_score)
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_match = match_item

    return best_match


def _pick_context_paragraph(
    mention_box: Sequence[float],
    page_paragraphs: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not page_paragraphs:
        return None

    containing = [
        paragraph
        for paragraph in page_paragraphs
        if _contains_box(paragraph["box"], mention_box)
    ]
    if containing:
        return min(containing, key=lambda paragraph: _box_area(paragraph["box"]))

    iou_candidates: List[Tuple[float, Dict[str, Any]]] = []
    for paragraph in page_paragraphs:
        iou = _box_iou(paragraph["box"], mention_box)
        if iou >= 0.08:
            iou_candidates.append((iou, paragraph))
    if iou_candidates:
        iou_candidates.sort(
            key=lambda item: (-item[0], _box_area(item[1]["box"]))
        )
        return iou_candidates[0][1]

    overlap_candidates: List[Tuple[float, Dict[str, Any]]] = []
    for paragraph in page_paragraphs:
        overlap = _overlap_ratio(paragraph["box"], mention_box)
        if overlap >= 0.2:
            overlap_candidates.append((overlap, paragraph))
    if overlap_candidates:
        overlap_candidates.sort(
            key=lambda item: (-item[0], _box_area(item[1]["box"]))
        )
        return overlap_candidates[0][1]

    return None


def build_references_data(
    *,
    references: Sequence[Dict[str, Any]],
    snippets: Sequence[Dict[str, Any]],
    layers: Dict[str, Any],
    references_numbered: bool = False,
) -> Dict[str, Any]:
    bibliography_items = _layer_items(layers, "bibliographies")
    token_items = _layer_items(layers, "tokens")
    row_items = _layer_items(layers, "rows")
    paragraph_items = _layer_items(layers, "paragraphs")
    bibliography_anchor: Optional[Tuple[int, float]] = None
    if bibliography_items:
        first_bibliography_item = min(
            bibliography_items,
            key=lambda item: (int(item.get("page", 10**6)), float(item["box"][1])),
        )
        bibliography_anchor = (
            int(first_bibliography_item.get("page", 0)),
            float(first_bibliography_item["box"][1]),
        )

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
    seen_mentions: set[Tuple[Any, ...]] = set()
    mention_text_key_max_len = 220

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
            token_items,
            row_items,
            paragraph_items,
        )
        mention_page = (
            mention_anchor["page"]
            if mention_anchor is not None
            else page_hint
        )
        mention_box = mention_anchor["box"] if mention_anchor is not None else None
        mention_y = _to_float(mention_box[1]) if mention_box is not None else None

        if mention_y is not None and mention_y < 0.05:
            continue
        if mention_y is not None and mention_y > 0.95:
            continue
        if is_inside_bibliography(
            {"page": mention_page, "box": mention_box},
            bibliography_items,
        ):
            continue
        if is_after_bibliography(mention_page, mention_y, bibliography_anchor):
            continue

        for mention_pos, ref_id in enumerate(dedup_ref_ids, start=1):
            quantized_mention_box = _quantize_box(mention_box)
            if quantized_mention_box is not None:
                dedup_key: Tuple[Any, ...] = (
                    "box",
                    ref_id,
                    mention_page,
                    quantized_mention_box,
                )
            else:
                dedup_key = (
                    "text",
                    ref_id,
                    mention_page,
                    _normalize_mention_text(snippet_text)[:mention_text_key_max_len],
                )

            if dedup_key in seen_mentions:
                continue
            seen_mentions.add(dedup_key)

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

            best_context = _pick_context_paragraph(mention_box, page_paragraphs)
            if best_context is None:
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
    max_reference_index = max(references_by_index.keys(), default=0)
    if max_reference_index <= 0:
        max_reference_index = len(reference_entries)
    bibliography_start_page = (
        bibliography_anchor[0] + 1 if bibliography_anchor is not None else None
    )

    return {
        "references": reference_entries,
        "citations": citations,
        "contexts": contexts,
        "citation_style": "numeric" if references_numbered else "non_numeric",
        "max_reference_index": max_reference_index,
        "bibliography_start_page": bibliography_start_page,
    }
