# Reference Regression Summary

- Run ID: `20260403-173421`
- Timestamp: `2026-04-03T17:34:21.406816+00:00`
- Dataset: `/Users/jorge/Documents/TFG/TFG/scripts/reference_regression_dataset.json`
- Dataset root: `/Users/jorge/Documents/TFG/TFG/tfg_project/citations/static/citations/PDFs-Reales`
- Dataset filter: `all`
- Engine requested: `papermage`
- Git revision: `1238cae`
- Total papers: `4`
- OK/WARN/FAIL: `0` / `3` / `1`

- Curated: `2` papers | OK/WARN/FAIL `0` / `2` / `0`
- Exploratory: `2` papers | OK/WARN/FAIL `0` / `1` / `1`

## Curated

| paper | expected | detected | last idx | rows_raw % | fallback % | inside bib % | doi % | engine | status | notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| brackmann_2017 | 37 | 37 | 37 | 0.00 | 100.00 | 0.00 | 51.35 | papermage->papermage | WARN | Caso base numerico ya iterado varias veces. |
| education_12_00179_v3 | 11 | 11 | 11 | 0.00 | 100.00 | 0.00 | 0.00 | papermage->papermage | WARN | Caso corto numerico con debug previo en el repo. |

## Exploratory

| paper | expected | detected | last idx | rows_raw % | fallback % | inside bib % | doi % | engine | status | notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| emnlp_demo_2023 | - | 6 | - | 0.00 | 50.00 | 50.00 | 0.00 | papermage->papermage | WARN | Paper del corpus real sin expectativa fijada todavia. |
| li_2020_stem | - | 4 | - | 0.00 | 100.00 | 0.00 | 75.00 | papermage->papermage | FAIL | PDF real del corpus base; expectativa de referencias pendiente de fijar. |
