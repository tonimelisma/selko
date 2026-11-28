GOVERNS: backend/selko/services/llm_gateway.py backend/selko/services/llm_provider.py backend/selko/services/llm_logging.py backend/selko/services/event_processing.py backend/selko/services/format_conversion.py

# LLM Integration — Multi-Provider Architecture

## Overview

Selko uses a provider-agnostic LLM abstraction layer (`LLMProvider` +
`LLMGateway`) with an explicit `ModelSpec` / `ThinkingConfig` registry.
Production calendar extraction uses **validated primary → fallback routing**
(`LLMGateway.call_validated`): three primary attempts for transient failures,
immediate fallback for empty/invalid/schema-echo/truncated output, and two
fallback attempts for transient failures only. Fallback must be a different
provider.

Production defaults (eval-backed Oct 2026: Haiku 5.5 extract 76 pass / 12
partial / 0 fail vs gemini-3.5-flash-lite 69 / 16 / 3; compare 21/23 each;
merge 5.0 each; about half the cost). Sonnet 5.5 scored 78 / 9 / 1 and 22/23
at roughly 17x Haiku's cost, so it is registered but not the default:

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-haiku-5-5
LLM_THINKING=low
LLM_FALLBACK_PROVIDER=none
```

Production runs on Claude alone (Nov 2026). `none` is explicit on purpose: an
unset fallback is filled from the provisional pairing in `config.py`
(Anthropic → Gemini). With no fallback, a refusal (`stop_reason: "refusal"`,
logged as `[refusal] category=…`) or exhausted transient retries fail the
attempt, and the email is retried by `fail_email_processing` backoff.

Every provider that can receive email content must be named in the public
privacy policy (`frontend/src/routes/privacy/+page.svelte`). Changing the
primary or fallback provider is a privacy-policy change too.

### Claude-specific decisions (measured Nov 2026)

- **Prompt shape.** Extraction instructions are a `SystemText` part, which the
  Anthropic provider sends as the `system` prompt (other providers see a plain
  string). The user turn is attachments first, then `<email_context>` and
  `<email_body>`. The system prompt is identical for every email, so it can be
  cached once traffic justifies it. Eval at `low`: extract 77/11/0 against the
  old prompt's 76/12/0. The borderline deadline fixture
  `credential_maintenance_deadlines_07` went from 1/8 to 3/8 over eight runs.
- **Effort: `low`.** `medium` scored worse (72/15/1), and cost and latency
  were higher. Haiku 5.5's default is `medium`, so `LLM_THINKING=low` must stay
  explicit.
- **No structured outputs (`output_config.format`).** They were tried and
  rejected. With the format constrained, Haiku 5.5 at `low` often skips
  thinking entirely: about 26 output tokens, `{"events_found": false, ...}`,
  against roughly 600 tokens with thinking when the JSON is prompt-instructed.
  Over eight runs, `government_comment_period_13` dropped from 8/8 to 0/8 on
  the old prompt and from 8/8 to 4/8 on the new one; `medium` effort recovered
  it only to 6/8. Prompt-instructed JSON parsed in every eval and production
  call, so the guarantee fixed nothing observed. Re-measure before adding them.
- **No prompt caching yet.** About one call every 25 minutes against a
  5-minute cache TTL means every call would pay the write premium and almost
  never hit. Revisit if bulk backfills become common.
- **Schema text stays as rendered (audited Nov 2026).** The Anthropic provider
  appends the schema as Python `str(dict)` under "You MUST respond with valid
  JSON". Rendering it as real JSON with plain wording was measured and not
  shipped: no fixture improved, and `survey_request_09` went from 13/13 to 13/15
  (two false-positive "survey closes" events). Re-measure before changing it.
- **Text attachments are sent as text.** `text/plain`, `text/csv`,
  `text/markdown` and TSV attachments become `<attachment filename="…">` text
  blocks (capped at 40K characters). They used to be wrapped as images and
  discarded by the converter, so an agenda in a `.txt` file never reached the
  model.
- **Eval fixtures and time zones.** A fixture without `user_timezone` runs as
  `America/New_York`. When the email states a zone (PST, "Pacific Time"), the
  expected times are the user-zone equivalents; when it states none, times are
  copied as written.

> The multimodal/image-processing material below describes the email-attachment pipeline; email is the only input ([ADR 0017](../adr/0017-email-is-the-only-input.md)).

### Current registry models (preferred low/minimal thinking each)

| Provider | Env Var Key | Model ID | Preferred thinking |
|----------|-------------|----------|--------------------|
| Gemini | `GEMINI_API_KEY` | `gemini-3.5-flash-lite`, `gemini-3.6-flash`, … | minimal |
| Qwen | `ALIBABA_API_KEY` | `qwen3.7-flash`, `qwen3.7-plus`, … | low budget |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-luna`, `gpt-5.6-terra`, … | low |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` (default), `claude-sonnet-5-5`, `claude-sonnet-5`, `claude-haiku-4-5` | adaptive low |
| Moonshot | `MOONSHOT_API_KEY` | `kimi-k3`, `kimi-k2.5`, `kimi-k2.6`, `kimi-k2.7-code` | effort / thinking toggle |
| Z.AI | `ZAI_API_KEY` | `glm-5.2`, … | toggle |
| xAI | `XAI_API_KEY` | `grok-4.5`, … | low |
| DeepSeek / MiniMax / Meta / Tinker | matching keys | see registry | varies |

See `backend/selko/services/llm_provider.py` for the full `MODEL_SPECS` / `MODEL_REGISTRY`.

### All-day materialization

LLM extractions `all_day: true` events remain source truth in
`event_sources.extracted_data`. A single user preference
(`user_calendar_settings.all_day_display_mode`) materializes the `events` row
as all-day or a timed window. The materialization rules and the
primary/fallback model routing they depend on are described above and in
`backend/selko/services/calendar_policy.py`.

Gemini setup research (SDK choice, OAuth scopes, multimodal requests) from when Gemini was the
default provider: [docs/research/2026-02-15-gemini-email-analysis-setup.md](../research/2026-02-15-gemini-email-analysis-setup.md).
