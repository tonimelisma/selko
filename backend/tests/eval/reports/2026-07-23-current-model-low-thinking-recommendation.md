# Current-model low-thinking recommendation

**Date:** 2026-07-23  
**Status:** Complete (Stage A/B corpus run; Stage C compare/merge included for all survivors)  
**Manifest:** `20260723T065010Z-e581a47d`  
**Plan:** `docs/specs/calendar-policy-llm-fallback-and-incremental-evals.md` WS7

## Matrix actually run

One preferred low/minimal thinking setting per registry model with a working API key:

| Provider | Model | Thinking | Notes |
|---|---|---|---|
| gemini | gemini-3.5-flash-lite | minimal | |
| gemini | gemini-3.6-flash | minimal | |
| openai | gpt-5.6-luna | low | |
| openai | gpt-5.6-terra | low | |
| anthropic | claude-sonnet-5 | low | |
| qwen | qwen3.6-flash | low | |
| qwen | qwen3.7-plus | low | |
| meta | muse-spark-1.1 | minimal | Verified live (`models.list` + structured JSON) |
| tinker | inkling | low | API model `thinkingmachines/Inkling` |

**Excluded this run**

| Provider | Reason |
|---|---|
| xai / grok-4.5 | No `XAI_API_KEY` in `.env` |
| zai / glm-5.2 | Preflight 401 (`身份验证失败`) |

## Cache / spend

- Idempotent content-addressed cache (WS5): resume after Meta cost-`None` crash was mostly HIT for finished models.
- Measured aggregate cost for the completed population: **~$6.24** (6 unknown-cost cells from Meta protocol failures).
- Failed calls are not written to the canonical inference cache.

## Results (extract / compare / merge)

| Model | Extract P/Par/F | Compare | Merge | Extract $ | Extract p50-ish API |
|---|---:|---:|---:|---:|---|
| **gemini-3.6-flash** | **78 / 7 / 0** | 15/0/0 | 15/0/0 | $0.73 | ~3.5s |
| claude-sonnet-5 | 76 / 8 / 1 | 15/0/0 | 15/0/0 | $0.84 | ~4.1s |
| qwen3.7-plus | 76 / 8 / 1 | 15/0/0 | 15/0/0 | $0.27 | ~29s |
| gemini-3.5-flash-lite | 75 / 7 / 3 | 15/0/0 | 15/0/0 | $0.11 | ~1.4s |
| gpt-5.6-terra | 72 / 9 / 4 | 15/0/0 | 15/0/0 | $1.43 | ~2.7s |
| muse-spark-1.1 | 65 / 14 / 6 | 15/0/0 | 15/0/0 | $0.42 | ~8.1s |
| qwen3.6-flash | 63 / 20 / 2 | 15/0/0 | 15/0/0 | $0.08 | ~14s |
| inkling | 62 / 20 / 3 | 15/0/0 | 15/0/0 | $0.18 | ~15s |
| gpt-5.6-luna | 60 / 17 / 8 | 15/0/0 | 15/0/0 | $1.55 | ~2.6s |

Aggregate: extract 627 PASS / 110 PARTIAL / 28 FAIL; compare 135/135; merge avg 5.0/5.

### Production fixtures

- `school/water_day_all_day_01` — passed on the quality leaders (kept `all_day: true`).
- `no_events/malformed_schema_echo_source_01` — passed on quality leaders (no false-positive events).

### Meta / Tinker notes

- **Muse Spark** is production-usable for text + many images, but several PDF-rendered / large-image fixtures returned HTTP 400 (`unsupported…`). Those failures were skipped from the canonical cache.
- **Inkling** completed the corpus with weaker extract quality and slower latency; fine as an experimental candidate, not a production primary.

## Recommended production routes

1. **Primary:** `gemini` / `gemini-3.6-flash` / thinking `minimal`  
   Best extract reliability this run (**0 hard fails**, most PASSes). Compare/merge perfect. Mid cost, good latency.
2. **Fallback:** `anthropic` / `claude-sonnet-5` / thinking `low`  
   Different provider (required). Near-tied extract quality, strong structured-output history, perfect compare/merge.

### Alternates (if you optimize differently)

- **Cheapest near-primary quality:** `qwen` / `qwen3.7-plus` / `low` — same extract P/Par/F as Sonnet at ~⅓ the $ but ~7× slower; use only if latency is acceptable.
- **High-volume cheap primary:** `gemini` / `gemini-3.5-flash-lite` / `minimal` — excellent $/quality, 3 hard fails; keep Sonnet or 3.6 as fallback.
- **Do not** promote Luna, Inkling, or Muse Spark to primary on this evidence.

## Retry policy (locked, already implemented)

- Primary: 3 total attempts for transient failures
- Empty / invalid JSON / schema echo / truncation / schema validation → immediate fallback after one primary attempt
- Fallback: 2 total attempts for transient failures only
- Database / persistence failures never invoke another model

## Environment configuration (no secrets)

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash
LLM_THINKING=minimal

LLM_FALLBACK_PROVIDER=anthropic
LLM_FALLBACK_MODEL=claude-sonnet-5
LLM_FALLBACK_THINKING=low

LLM_PRIMARY_MAX_ATTEMPTS=3
LLM_FALLBACK_MAX_ATTEMPTS=2
```

## Known limitations / when to retest

- Meta Spark PDF/image 400s need adapter/MIME investigation before Meta is fallback-eligible.
- Z.AI key is invalid; retest GLM-5.2 after rotating the key.
- xAI Grok 4.5 not scored (missing key).
- Evidence that would justify another thinking level: Stage B semantic misses concentrated on date/all-day fixtures at the preferred low/minimal setting with protocol success — then retest that model only at the next level.
