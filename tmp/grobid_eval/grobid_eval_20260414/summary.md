# GROBID Evaluation `grobid_eval_20260414`

## Config

- Base URL: http://localhost:8070
- Timeout (s): 240
- PDFs evaluados: 9
- Buckets problematicos: low_alpha_or_short_noise, small_reference_set, header_not_found_fallback

## Health

- /api/version: ok=True status=200 error=-
- /api/isalive: ok=True status=200 error=-
- /api/health: ok=True status=200 error=-

## Q1: processReferences

- Problematicos: 6
- Rescatados: 3 (ICGSE2017.pdf, s10664-011-9181-9.pdf, s41979-020-00044-w.pdf)
- Avg delta refs: -3.56
- Avg delta valid: 6.89
- Respuesta: si

## Q2: processFulltextDocument

- Comparables: 9
- Papers con valor adicional: 9 (1904.02703v3.pdf, ICGSE2017.pdf, JScientometRes-14-3-838.pdf, Kelemen_Subramanian_19.09.2023.pdf, s10664-011-9181-9.pdf, s41979-020-00044-w.pdf, 1610.06546v3.pdf, 2002.12508v3.pdf, 2017-CT-development-computational-thinking_RG.pdf)
- Avg delta refs: 0.00
- Avg delta valid: 0.00
- Respuesta: si

## Q3: processCitationList vs refextract

- Papers comparados: 9
- Metric wins (citation_list): title=1, authors=4, year=2, doi=3, almost_empty=0
- Delta sums: title=-73, authors=+6, year=-88, doi=+27, almost_empty=+12
- Respuesta: no

## Recomendacion

- Decision final: aporta_solo_como_fallback
