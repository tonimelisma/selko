# 0009. LLM-centric extraction; production runs one Anthropic model with no fallback

- Status: accepted
- Date: 2026-11-28

## Context and problem

All intelligence (reading PDFs and images, extracting dates and places, classifying, matching
updates) can be done by one multimodal LLM. Every provider that can receive email content must be
named in the public privacy policy. Requirements: [SEL-100..108](../requirements/extraction.md),
[SEL-735..741](../requirements/privacy.md).

## Decision drivers

- No separate OCR service.
- The privacy policy names every recipient of email content.
- Measured quality per model through the evals.

## Considered options

### One multimodal model in production, `claude-haiku-5-5`, with `LLM_FALLBACK_PROVIDER=none` (chosen)

- Good: one data recipient to disclose; evals target exactly what runs.
- Bad: a provider outage stops extraction until it recovers (work retries).
- Failure modes: an unset fallback is auto-filled by the registry, so `none` must stay explicit or a second provider would silently receive mail.

### A primary plus an automatic fallback provider

- Good: survives one provider's outage.
- Bad: two recipients of user mail; the policy must name both.
- Failure modes: quality differs silently between providers.

## Decision

Extraction runs through the multi-provider gateway (`selko.services.llm_gateway`); production runs
`claude-haiku-5-5` only, with `LLM_FALLBACK_PROVIDER=none`. Changing the model or adding a provider
that can receive email content is a privacy-policy change. A production LLM failure becomes an
anonymized eval fixture with hand-written expected output.

## Consequences

Other providers' keys are read only for eval comparisons. The code's defaults differ from
production (#457 tracks making the default match).

## Confirmation

`backend/tests/test_llm_gateway_fallback.py`, `backend/tests/test_config.py` (SEL-101, SEL-741);
the privacy page test (SEL-736, SEL-737); the evals (`docs/design/evals.md`).

## Retirement proof

Evals showing another model is better on quality, cost and latency, with the policy updated.

## Reversal plan

Set `LLM_PROVIDER`/`LLM_MODEL` to another registered model and update `/privacy` in the same change.
