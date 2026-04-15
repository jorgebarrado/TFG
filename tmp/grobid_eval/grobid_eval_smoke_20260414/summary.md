# GROBID Evaluation `grobid_eval_smoke_20260414`

## Config

- Base URL: http://localhost:8070
- Timeout (s): 180
- PDFs evaluados: 1
- Buckets problematicos: low_alpha_or_short_noise, small_reference_set, header_not_found_fallback

## Health

- /api/version: ok=True status=200 error=-
- /api/isalive: ok=True status=200 error=-
- /api/health: ok=True status=200 error=-

## Q1: processReferences

- Problematicos: 1
- Rescatados: 0 (ninguno)
- Avg delta refs: 3.00
- Avg delta valid: 2.00
- Respuesta: no

## Q2: processFulltextDocument

- Comparables: 1
- Papers con valor adicional: 1 (2103.02202v3.pdf)
- Avg delta refs: 0.00
- Avg delta valid: 0.00
- Respuesta: si

## Q3: processCitationList vs refextract

- Papers comparados: 1
- Metric wins (citation_list): title=0, authors=0, year=0, doi=0, almost_empty=0
- Delta sums: title=-29, authors=-7, year=-28, doi=-13, almost_empty=+0
- Respuesta: no

## Recomendacion

- Decision final: no_aporta_suficiente
