# Aggregate By Input Bucket

Global metrics can hide parser behavior differences when papers start from degraded reference text. Use this breakdown to compare parsers per input quality bucket.

## clean_input

- Papers: 9
- Total references: 254
- Papers list: 1610.06546v3.pdf, 2002.12508v3.pdf, 2017-CT-development-computational-thinking_RG.pdf, 2023.emnlp-demo.45.pdf, 2103.02202v3.pdf, 2107.02194v2.pdf, a0e5d5ee6a06c0d9bd4b39ee64dd8b58e861.pdf, education-12-00179-v3.pdf, qt5bm130vv.pdf
- Observations: Baseline bucket with cleaner extracted references.

### refextract

- Status: ok
- Total references processed: 254
- Title non-empty: 254
- Authors non-empty: 203
- Year non-empty: 249
- DOI non-empty: 53
- Almost empty: 0
- Parser observations: Executed with refextract string mode over already segmented references. | Refextract required a local magic shim because libmagic is not installed on this Windows environment. | Refextract produced multiple candidate parses for 4 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 4 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | DOI coverage is relatively strong. | Executed with refextract string mode over already segmented references. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 4 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 4 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 53 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 10 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 1 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string.

### anystyle

- Status: unavailable
- Total references processed: 254
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 254
- Parser observations: AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | anystyle status: unavailable | A large share of entries remained close to raw text.

### llm

- Status: unavailable
- Total references processed: 254
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 254
- Parser observations: LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | llm status: unavailable | A large share of entries remained close to raw text.

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

- Papers: 2
- Total references: 6
- Papers list: s10664-011-9181-9.pdf, s41979-020-00044-w.pdf

### refextract

- Status: ok
- Total references processed: 6
- Title non-empty: 6
- Authors non-empty: 5
- Year non-empty: 6
- DOI non-empty: 3
- Almost empty: 0
- Parser observations: Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 1 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 3 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | DOI coverage is relatively strong. | DOI coverage is relatively strong.

### anystyle

- Status: unavailable
- Total references processed: 6
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 6
- Parser observations: AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | anystyle status: unavailable | A large share of entries remained close to raw text.

### llm

- Status: unavailable
- Total references processed: 6
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 6
- Parser observations: LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | llm status: unavailable | A large share of entries remained close to raw text.

## low_alpha_or_short_noise

- Papers: 3
- Total references: 300
- Papers list: 1904.02703v3.pdf, JScientometRes-14-3-838.pdf, Kelemen_Subramanian_19.09.2023.pdf
- Observations: Coverage drops here should be interpreted primarily as input degradation effects, not only parser capability limits.

### refextract

- Status: ok
- Total references processed: 300
- Title non-empty: 238
- Authors non-empty: 129
- Year non-empty: 230
- DOI non-empty: 56
- Almost empty: 40
- Parser observations: Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 1 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | DOI coverage is relatively strong. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 71 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string. | Executed with refextract string mode over already segmented references. | Refextract produced multiple candidate parses for 15 segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string.

### anystyle

- Status: unavailable
- Total references processed: 300
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 300
- Parser observations: AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | anystyle status: unavailable | A large share of entries remained close to raw text.

### llm

- Status: unavailable
- Total references processed: 300
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 300
- Parser observations: LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | llm status: unavailable | A large share of entries remained close to raw text.

## header_not_found_fallback

- Papers: 1
- Total references: 54
- Papers list: ICGSE2017.pdf

### refextract

- Status: ok
- Total references processed: 54
- Title non-empty: 54
- Authors non-empty: 54
- Year non-empty: 53
- DOI non-empty: 0
- Almost empty: 0
- Parser observations: Executed with refextract string mode over already segmented references.

### anystyle

- Status: unavailable
- Total references processed: 54
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 54
- Parser observations: AnyStyle was not executed because Ruby/anystyle-cli is absent. | anystyle status: unavailable | A large share of entries remained close to raw text. | anystyle status: unavailable | A large share of entries remained close to raw text.

### llm

- Status: unavailable
- Total references processed: 54
- Title non-empty: 0
- Authors non-empty: 0
- Year non-empty: 0
- DOI non-empty: 0
- Almost empty: 54
- Parser observations: LLM prompt was generated but no API call was made. | llm status: unavailable | A large share of entries remained close to raw text. | llm status: unavailable | A large share of entries remained close to raw text.

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
