# Aggregate By Input Bucket

Global metrics can hide parser behavior differences when papers start from degraded reference text. Use this breakdown to compare parsers per input quality bucket.

## clean_input

- Papers: 1
- Total references: 37
- Papers list: 2017-CT-development-computational-thinking_RG.pdf
- Observations: Baseline bucket with cleaner extracted references.

### refextract

- Status: ok
- Total references processed: 37
- Title non-empty: 37
- Authors non-empty: 13
- Year non-empty: 37
- DOI non-empty: 17
- Almost empty: 0
- Parser observations: Executed with refextract string mode over already segmented references. | Refextract required a local magic shim because libmagic is not installed on this Windows environment.

### anystyle

- Status: unavailable
- Total references processed: 37
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 37
- Parser observations: AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | anystyle status: unavailable | A large share of entries remained close to raw text.

### llm

- Status: unavailable
- Total references processed: 37
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 37
- Parser observations: LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | llm status: unavailable | A large share of entries remained close to raw text.

## numeric_noise

- Papers: 0
- Total references: 0
- Papers list: (none)
- Observations: No papers matched this bucket in this run.

### refextract

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: refextract status: unknown

### anystyle

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: anystyle status: unknown

### llm

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: llm status: unknown

## likely_fused_references

- Papers: 0
- Total references: 0
- Papers list: (none)
- Observations: No papers matched this bucket in this run.

### refextract

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: refextract status: unknown

### anystyle

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: anystyle status: unknown

### llm

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: llm status: unknown

## small_reference_set

- Papers: 0
- Total references: 0
- Papers list: (none)
- Observations: No papers matched this bucket in this run.

### refextract

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: refextract status: unknown

### anystyle

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: anystyle status: unknown

### llm

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: llm status: unknown

## low_alpha_or_short_noise

- Papers: 0
- Total references: 0
- Papers list: (none)
- Observations: No papers matched this bucket in this run.

### refextract

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: refextract status: unknown

### anystyle

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: anystyle status: unknown

### llm

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: llm status: unknown

## header_not_found_fallback

- Papers: 0
- Total references: 0
- Papers list: (none)
- Observations: No papers matched this bucket in this run.

### refextract

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: refextract status: unknown

### anystyle

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: anystyle status: unknown

### llm

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: llm status: unknown

## mixed_issues

- Papers: 0
- Total references: 0
- Papers list: (none)
- Observations: No papers matched this bucket in this run.

### refextract

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: refextract status: unknown

### anystyle

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: anystyle status: unknown

### llm

- Status: unknown
- Total references processed: 0
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: llm status: unknown
