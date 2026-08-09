# Evaluation Report: support-routing-v1

> Deterministic CI evidence only. These observations are not live OpenAI measurements.

## Evidence

| Field | Value |
| --- | --- |
| Observation version | `support-routing-v1-deterministic-v1` |
| Captured at | `2026-08-09T00:00:00Z` |
| Source | `deterministic_ci` |
| Taxonomy | `general-technical-support-v1` |
| Collection | `support@faq-33-v1` |

## Selected Operating Point

| Setting | Value |
| --- | ---: |
| Similarity threshold | 0.84 |
| Similarity margin | 0.08 |
| Scope confidence threshold | 0.75 |

## Objective Metrics

| Metric | Value |
| --- | ---: |
| Retrieval Recall@1 | 0.818182 |
| Retrieval Recall@3 | 1.000000 |
| Retrieval MRR | 0.909091 |
| Route accuracy | 1.000000 |
| Local precision | 1.000000 |
| Local recall | 1.000000 |
| False-local count | 0 |
| False-local rate | 0.000000 |
| Scope accuracy | 1.000000 |
| Scope in-domain F1 | 1.000000 |
| Attack block rate | 1.000000 |
| Benign guardrail false-positive rate | 0.000000 |
| Schema-valid response rate | 1.000000 |
| Latency p50 | 49 ms |
| Latency p95 | 439 ms |

## Usage by Route

| Route | Cases | Input tokens | Output tokens | Estimated cost (USD) |
| --- | ---: | ---: | ---: | ---: |
| compliance | 4 | 0 | 0 | 0.00000000 |
| error | 4 | 0 | 0 | 0.00000000 |
| local | 8 | 0 | 0 | 0.00000000 |
| openai | 9 | 670 | 915 | 0.00000000 |

## Subjective Fallback Review

- Reviewed answers: 9
- Reviews: 18
- Mean relevance: 4.777778
- Mean correctness: 4.333333
- Mean clarity: 4.611111
- Mean safety: 5.000000
- Mean consistency: 4.777778
- Unsupported-claim rate: 0.000000

## Known Weak Cases

- `faq-phishing`: similarity_boundary
- `faq-notification-settings`: similarity_boundary
- `near-email-change`: ambiguous_near_neighbor
- `near-two-factor`: ambiguous_near_neighbor
- `near-account-removal`: ambiguous_near_neighbor
- `near-account-removal`: margin_boundary
- `fallback-wifi`: similarity_boundary

## Limitations

- Observations use deterministic CI providers and recorded scores, not live OpenAI calls.
- Refresh the observation set with approved live-model captures before production tuning.
- Subjective review is a two-reviewer regression sample, not a broad human study.
