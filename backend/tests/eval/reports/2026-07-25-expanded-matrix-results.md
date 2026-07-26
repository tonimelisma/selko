# Expanded matrix eval results (2026-07-25)

29-model matrix. Content-addressed cache: prior completed cells were HIT
(gemini-3.6/3.5-lite, sonnet, luna/terra, qwen3.6/3.7-plus, muse, inkling —
except a few muse PDF + inkling misses). New models + previously skipped
glm-5.2 / grok-4.5 were MISS and billed.

Manifest: `20260726T021248Z-a5c7335c`  
Aggregate reported cost: **$11.47** (includes cached cell costs in totals).

Score = pass / partial / fail. Vision models: extract n=85. Text-only
(DeepSeek V4, GLM-5.x/4.5-air): extract n≈74 (image fixtures skipped).

| Model | Think | Extract | Compare | Merge | Ext $ | Total $ |
|---|---|---:|---:|---:|---:|---:|
| gemini-3.6-flash | minimal | 78/7/0 | 15/0/0 | 15/0/0 | 0.73 | **0.77** |
| qwen3.7-plus | low | 76/8/1 | 15/0/0 | 15/0/0 | 0.27 | **0.34** |
| claude-sonnet-5 | low | 76/8/1 | 15/0/0 | 15/0/0 | 0.84 | **0.92** |
| gemini-3.1-flash-lite | minimal | 75/8/2 | 15/0/0 | 15/0/0 | 0.09 | **0.10** |
| gemini-3.5-flash-lite | minimal | 75/7/3 | 15/0/0 | 15/0/0 | 0.11 | **0.13** |
| gemini-3.5-flash | minimal | 74/9/2 | 15/0/0 | 15/0/0 | 0.16 | **0.18** |
| claude-haiku-4-5 | low | 73/9/3 | 15/0/0 | 15/0/0 | 0.34 | **0.38** |
| gpt-5.6-terra | low | 72/9/4 | 15/0/0 | 15/0/0 | 1.43 | **1.57** |
| kimi-k3 | low | 71/11/3 | 15/0/0 | 15/0/0 | 1.03 | **1.17** |
| qwen3.7-flash | low | 66/17/2 | 15/0/0 | 15/0/0 | 0.08 | **0.10** |
| glm-4.6v | low | 66/15/4 | 15/0/0 | 15/0/0 | 0.27 | **0.32** |
| qwen3-vl-flash | low | 66/12/7 | 14/0/1 | 14/0/1 | 0.06 | **0.07** |
| grok-4.5 | low | 65/17/3 | 15/0/0 | 15/0/0 | 0.50 | **0.55** |
| muse-spark-1.1 | minimal | 65/14/6 | 15/0/0 | 15/0/0 | 0.42 | **0.51** |
| qwen3.6-flash | low | 63/20/2 | 15/0/0 | 15/0/0 | 0.08 | **0.10** |
| MiniMax-M2.7 | low | 63/14/8 | 15/0/0 | 15/0/0 | 0.12 | **0.14** |
| inkling | low | 62/20/3 | 15/0/0 | 15/0/0 | 0.18 | **0.20** |
| deepseek-v4-flash | low | 61/12/1† | 15/0/0 | 15/0/0 | 0.03 | **0.04** |
| gpt-5.6-luna | low | 60/17/8 | 15/0/0 | 15/0/0 | 1.55 | **1.70** |
| glm-4.5-air | low | 56/18/0† | 15/0/0 | 14/1/0 | 0.14 | **0.17** |
| deepseek-v4-pro | low | 54/18/2† | 15/0/0 | 15/0/0 | 0.12 | **0.14** |
| qwen3.5-flash | low | 53/22/10 | 15/0/0 | 15/0/0 | 0.08 | **0.11** |
| glm-5.1 | low | 52/22/0† | 15/0/0 | 15/0/0 | 0.43 | **0.51** |
| MiniMax-M3 | low | 52/22/11 | 8/0/7 | 15/0/0 | 0.14 | **0.15** |
| glm-5.2 | low | 51/22/1† | 15/0/0 | 15/0/0 | 0.62 | **0.71** |
| glm-5-turbo | low | 47/25/2† | 15/0/0 | 15/0/0 | 0.22 | **0.28** |
| kimi-k2.6 | low | 2/4/79 | 0/0/15 | 0/0/15 | 0.11 | **0.11** |
| kimi-k2.7-code | low | 0/0/85 | 0/0/15 | 0/0/15 | 0.00 | **0.00** |
| kimi-k2.5 | low | 0/0/85 | 0/0/15 | 0/0/15 | 0.00 | **0.00** |

† Text-only — image extract fixtures skipped.

## Notes

- **kimi-k2.5 / k2.6 / k2.7-code** largely failed validated calls (Moonshot 400 /
  transient). **kimi-k3** is fine with `json_object` + `reasoning_effort=low`.
- **Haiku** does not support Anthropic adaptive thinking; registry disables it
  for haiku only.
- **Z.AI** key alias: `ZHIPU_API_KEY` → `zai_api_key`.
- Soft spot: older Kimi SKUs need a Moonshot-specific adapter (no
  `reasoning_effort` / stricter schema) before re-eval is useful.

## Production pairing (chosen)

Cheap Pareto pick from this matrix (quality ≈ extract passes, cost = suite $):

| Role | Model | Think | Extract | Suite $ |
|---|---|---|---:|---:|
| Primary | `gemini-3.5-flash-lite` | minimal | 75/7/3 | **0.13** |
| Fallback | `qwen3.7-flash` | low | 66/17/2 | **0.10** |

Higher-quality (costlier) alternatives remain: primary `gemini-3.6-flash` /
fallback `qwen3.7-plus` or `claude-sonnet-5`.

## Provisional recommendation (board top — superseded for prod defaults)

| Role | Model | Why |
|---|---|---|
| Primary | `gemini-3.6-flash` / `minimal` | Best extract (78/7/0) |
| Cheap primary alt | `gemini-3.5-flash-lite` or `gemini-3.1-flash-lite` | ~same quality, ~$0.10–0.13 |
| Fallback | `claude-sonnet-5` / `low` or `qwen3.7-plus` / `low` | Same 76/8/1; plus is cheaper |
