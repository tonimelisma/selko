# Current-model low-thinking recommendation

**Date:** 2026-07-23  
**Status:** Provisional (Stage A/B full corpus not fully purchased in this increment)  
**Plan:** `docs/specs/calendar-policy-llm-fallback-and-incremental-evals.md` WS7

## Matrix actually configured

One preferred low/minimal thinking setting per current registry model
(`backend/tests/eval/eval_config.py` `EVAL_MODELS`):

| Provider | Model | Thinking |
|---|---|---|
| gemini | gemini-3.5-flash-lite | minimal |
| gemini | gemini-3.6-flash | minimal |
| openai | gpt-5.6-luna | low |
| openai | gpt-5.6-terra | low |
| anthropic | claude-sonnet-5 | low |
| qwen | qwen3.6-flash | low |
| qwen | qwen3.7-plus | low |
| zai | glm-5.2 | low |
| xai | grok-4.5 | low |

Excluded from the default matrix (per plan): GPT-5.6 Sol, MiniMax M2.5,
legacy Qwen 3/3.5/VL IDs, DeepSeek chat/reasoner, Grok 4.3, Claude Fable/Opus
as defaults, Meta Spark / Tinker Inkling pending authenticated capability checks.

## Cache / spend

Use:

```bash
uv run python -m backend.tests.eval.run_eval --all --all-operations --all-models --plan
```

Identical cells are content-addressed HITs (WS5). This report was authored
alongside registry + fixture landing; full Stage A/B spend depends on which
provider keys are present in the environment.

## New production fixtures

- `school/water_day_all_day_01` — Water Day stays `all_day=true`
- `no_events/malformed_schema_echo_source_01` — protocol / no-event source

## Recommended production routes (provisional)

Until Stage B shared-corpus scores finalize the choice:

1. **Primary:** `anthropic` / `claude-sonnet-5` / thinking `low`  
   Best known structured-output reliability for calendar extraction in prior
   Selko runs; adaptive low effort is explicit.
2. **Fallback:** `openai` / `gpt-5.6-terra` / thinking `low`  
   Different provider (required). Terra is the balanced GPT-5.6 ID; Sol is
   excluded. Always send `reasoning_effort=low` explicitly.

Alternate high-volume primary candidate after Stage B: `openai` /
`gpt-5.6-luna` / `low`, with fallback remaining a non-OpenAI provider
(`anthropic` / `claude-sonnet-5` / `low`).

## Retry policy (locked)

- Primary: 3 total attempts for transient failures
- Empty / invalid JSON / schema echo / truncation / schema validation →
  immediate fallback after one primary attempt
- Fallback: 2 total attempts for transient failures only
- Database / persistence failures never invoke another model

## Environment configuration (no secrets)

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-5
LLM_THINKING=low

LLM_FALLBACK_PROVIDER=openai
LLM_FALLBACK_MODEL=gpt-5.6-terra
LLM_FALLBACK_THINKING=low

LLM_PRIMARY_MAX_ATTEMPTS=3
LLM_FALLBACK_MAX_ATTEMPTS=2
```

## Known limitations / when to retest thinking

- Gemini 3.x cannot disable thinking; `none` maps to `minimal`.
- Qwen 3.6/3.7 thinking+structured-output compatibility should be confirmed
  in Stage A smoke before promoting Qwen to primary.
- xAI Grok 4.5 and Z.AI GLM-5.2 need authenticated smoke before production
  fallback eligibility.
- Evidence that would justify another thinking level: Stage B semantic misses
  concentrated on date/all-day fixtures at the preferred low/minimal setting
  with protocol success — then retest that model only at the next level.
