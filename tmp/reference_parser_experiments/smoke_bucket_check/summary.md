# Reference Parser Experiment `smoke_bucket_check`

## Config

- PDF selection mode: explicit_list
- PDFs selected: 1
- PDFs: 2017-CT-development-computational-thinking_RG.pdf
- Comparison limit: 3
- LLM model: gpt-4.1-mini

## Aggregate

### refextract

- Status: ok
- Total references processed: 37
- Title non-empty: 37
- Authors non-empty: 13
- Year non-empty: 37
- DOI non-empty: 17
- Almost empty: 0
- Observations: Executed with refextract string mode over already segmented references. | Refextract required a local magic shim because libmagic is not installed on this Windows environment.

### anystyle

- Status: unavailable
- Total references processed: 37
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 37
- Observations: AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | anystyle status: unavailable | A large share of entries remained close to raw text.

### llm

- Status: unavailable
- Total references processed: 37
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 37
- Observations: LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | llm status: unavailable | A large share of entries remained close to raw text.

## Input Quality Overview

- Total papers: 1
- Degraded papers: 0
- Papers with numeric-noise signal: 0
- Papers with likely-fused-references signal: 0
- Caveat: Global parser coverage can be misleading when raw reference input is degraded; consult per-bucket metrics before drawing integration conclusions.

### Papers By Primary Bucket

- clean_input: 1
- numeric_noise: 0
- likely_fused_references: 0
- small_reference_set: 0
- low_alpha_or_short_noise: 0
- header_not_found_fallback: 0
- mixed_issues: 0

## Aggregate By Bucket

### clean_input

- Papers: 1
- Total references: 37
- Papers list: 2017-CT-development-computational-thinking_RG.pdf
- refextract: title=37, authors=13, year=37, doi=17, almost_empty=0
- anystyle: title=0, authors=0, year=0, doi=0, almost_empty=37
- llm: title=0, authors=0, year=0, doi=0, almost_empty=37

## Recommendation

- Next candidate: llm
- Discard now: anystyle
- Rationale: refextract was the only alternative executed end-to-end in this environment; LLM wiring is ready but no API execution happened because credentials are missing; AnyStyle is blocked by the lack of Ruby/anystyle-cli on this machine. For this stack, the most promising next real integration candidate is an LLM parser over already segmented references because it matches the desired architecture, avoids a Ruby dependency, and can return a schema tailored to CiteCheck. Refextract is useful as a bounded benchmark, but its parsing is biased toward journal-style patterns and required environment-specific shimming. AnyStyle should be deferred unless you provision a separate Ruby-capable sandbox specifically for it.
