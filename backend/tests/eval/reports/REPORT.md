# Selko LLM Eval Report
Generated: 2026-02-21T07:06:50.094922+00:00

## Eval Run Overview

| Metric | Value |
|--------|-------|
| **Total Eval Cost** | **$4.1236** |
| Total Evals | 1692 (1242 extract, 225 compare, 225 merge) |
| Models Tested | 29 |
| Total Tokens | 2,781,202 |
| Total API Time | 12952s |
| Code Hash | 274b820b8ecc, 2bf536dc0a22, 6e8b4c59aa00, unknown |

## Model Comparison

| Model | Extract | Compare | Merge | Cost | Avg Latency |
|-------|---------|---------|-------|------|-------------|
| MiniMax-M2.5 (none) | 0/1 (0.0%) | - | - | $0.0000 | 11423ms |
| claude-haiku-4-5-20251001 (low) | 13/74 (17.6%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2204 | 2544ms |
| claude-haiku-4-5-20251001 (none) | 0/3 (0.0%) | - | - | $0.0146 | 4734ms |
| claude-sonnet-4-6 (low) | 17/48 (35.4%) | - | - | $0.4236 | 3604ms |
| claude-sonnet-4-6 (none) | 33/74 (44.6%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $1.0069 | 4595ms |
| deepseek-chat (none) | 0/1 (0.0%) | - | - | $0.0000 | 6276ms |
| gemini-3-flash-preview (low) | 9/148 (6.1%) | 12/30 (40.0%) | 0/30 (0.0 avg) | $0.0388 | 3399ms |
| gemini-3-flash-preview (medium) | 0/74 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0039 | 3422ms |
| gemini-3-flash-preview (none) | 0/74 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0038 | 2767ms |
| glm-4.6v-flash (low) | 9/73 (12.3%) | 0/15 (0.0%) | 1/15 (0.3 avg) | $0.0000 | 14074ms |
| glm-4.6v-flash (none) | 0/3 (0.0%) | - | - | $0.0000 | 36190ms |
| gpt-4o-mini (low) | 0/18 (0.0%) | - | - | $0.0044 | 4150ms |
| gpt-5-mini (low) | 24/74 (32.4%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.1310 | 8082ms |
| gpt-5-mini (medium) | 26/74 (35.1%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2247 | 14260ms |
| gpt-5-nano (low) | 17/108 (15.7%) | 15/15 (100.0%) | 13/15 (4.9 avg) | $0.0760 | 10902ms |
| gpt-5-nano (medium) | 21/74 (28.4%) | 14/15 (93.3%) | 15/15 (5.0 avg) | $0.1150 | 21292ms |
| gpt-5.2 (low) | 23/74 (31.1%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.6718 | 5126ms |
| gpt-5.2 (medium) | 21/74 (28.4%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.8605 | 7442ms |
| kimi-k2.5 (low) | 0/73 (0.0%) | 14/15 (93.3%) | 9/15 (4.2 avg) | $0.0940 | 6572ms |
| kimi-k2.5 (none) | 0/3 (0.0%) | - | - | $0.0219 | 41939ms |
| qwen-vl-max (none) | 0/3 (0.0%) | - | - | $0.0118 | 21302ms |
| qwen3-vl-flash (low) | 8/73 (11.0%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.0262 | 3266ms |
| qwen3-vl-flash (none) | 0/3 (0.0%) | - | - | $0.0021 | 8075ms |
| qwen3-vl-plus (low) | 0/3 (0.0%) | - | - | $0.0286 | 32654ms |
| qwen3-vl-plus (medium) | 0/3 (0.0%) | - | - | $0.0453 | 53943ms |
| qwen3-vl-plus (none) | 0/3 (0.0%) | - | - | $0.0095 | 10558ms |
| qwen3.5-plus (low) | 0/3 (0.0%) | - | - | $0.0332 | 18636ms |
| qwen3.5-plus (medium) | 0/3 (0.0%) | - | - | $0.0378 | 23866ms |
| qwen3.5-plus (none) | 0/3 (0.0%) | - | - | $0.0176 | 8327ms |
| **TOTAL** | | | | **$4.1236** | |

*Note: Models ran different numbers of extract fixtures (1, 3, 18, 48, 73, 74, 108, 148). Text-only models skip vision fixtures (images, PDFs), so pass rates are not directly comparable.*

## Extraction Results

### All Fixtures

| Model | Pass | Partial | Fail | Avg Rating | Cost |
|-------|------|---------|------|------------|------|
| MiniMax-M2.5 (none) | 0 | 0 | 1 | 0.0/5 | $0.0000 |
| claude-haiku-4-5-20251001 (low) | 13 | 48 | 13 | 3.2/5 | $0.1902 |
| claude-haiku-4-5-20251001 (none) | 0 | 3 | 0 | 3.0/5 | $0.0146 |
| claude-sonnet-4-6 (low) | 17 | 29 | 2 | 3.6/5 | $0.4236 |
| claude-sonnet-4-6 (none) | 33 | 38 | 3 | 3.8/5 | $0.8974 |
| deepseek-chat (none) | 0 | 0 | 1 | 0.0/5 | $0.0000 |
| gemini-3-flash-preview (low) | 9 | 60 | 79 | 1.8/5 | $0.0374 |
| gemini-3-flash-preview (medium) | 0 | 3 | 71 | 0.1/5 | $0.0026 |
| gemini-3-flash-preview (none) | 0 | 3 | 71 | 0.1/5 | $0.0024 |
| glm-4.6v-flash (low) | 9 | 5 | 59 | 0.9/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 3 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 18 | 0 | 4.0/5 | $0.0044 |
| gpt-5-mini (low) | 24 | 45 | 5 | 3.4/5 | $0.1167 |
| gpt-5-mini (medium) | 26 | 44 | 4 | 3.5/5 | $0.2006 |
| gpt-5-nano (low) | 17 | 83 | 8 | 3.3/5 | $0.0690 |
| gpt-5-nano (medium) | 21 | 45 | 8 | 3.3/5 | $0.0957 |
| gpt-5.2 (low) | 23 | 47 | 4 | 3.3/5 | $0.6059 |
| gpt-5.2 (medium) | 21 | 48 | 5 | 3.3/5 | $0.7874 |
| kimi-k2.5 (low) | 0 | 0 | 73 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 1 | 2.7/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 3 | 0 | 2.3/5 | $0.0118 |
| qwen3-vl-flash (low) | 8 | 53 | 12 | 3.4/5 | $0.0226 |
| qwen3-vl-flash (none) | 0 | 3 | 0 | 2.3/5 | $0.0021 |
| qwen3-vl-plus (low) | 0 | 3 | 0 | 3.0/5 | $0.0286 |
| qwen3-vl-plus (medium) | 0 | 0 | 3 | 0.0/5 | $0.0453 |
| qwen3-vl-plus (none) | 0 | 3 | 0 | 2.3/5 | $0.0095 |
| qwen3.5-plus (low) | 0 | 3 | 0 | 2.3/5 | $0.0332 |
| qwen3.5-plus (medium) | 0 | 2 | 1 | 1.7/5 | $0.0378 |
| qwen3.5-plus (none) | 0 | 2 | 1 | 1.7/5 | $0.0176 |

### Real-Life Fixtures Only

| Model | Pass | Partial | Fail | Avg Rating | Cost |
|-------|------|---------|------|------------|------|
| claude-haiku-4-5-20251001 (low) | 2 | 5 | 7 | 1.9/5 | $0.0455 |
| claude-haiku-4-5-20251001 (none) | 0 | 2 | 0 | 3.0/5 | $0.0125 |
| claude-sonnet-4-6 (low) | 0 | 2 | 0 | 3.0/5 | $0.0290 |
| claude-sonnet-4-6 (none) | 5 | 8 | 1 | 3.6/5 | $0.3311 |
| gemini-3-flash-preview (low) | 2 | 11 | 15 | 1.8/5 | $0.0227 |
| gemini-3-flash-preview (medium) | 0 | 2 | 12 | 0.4/5 | $0.0023 |
| gemini-3-flash-preview (none) | 0 | 2 | 12 | 0.4/5 | $0.0022 |
| glm-4.6v-flash (low) | 1 | 1 | 11 | 0.7/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 2 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 1 | 0 | 4.0/5 | $0.0006 |
| gpt-5-mini (low) | 2 | 10 | 2 | 2.6/5 | $0.0429 |
| gpt-5-mini (medium) | 2 | 10 | 2 | 2.8/5 | $0.0734 |
| gpt-5-nano (low) | 3 | 11 | 1 | 2.9/5 | $0.0109 |
| gpt-5-nano (medium) | 4 | 9 | 1 | 3.3/5 | $0.0282 |
| gpt-5.2 (low) | 3 | 10 | 1 | 2.9/5 | $0.2396 |
| gpt-5.2 (medium) | 3 | 10 | 1 | 3.1/5 | $0.3075 |
| kimi-k2.5 (low) | 0 | 0 | 13 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 0 | 4.0/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 2 | 0 | 2.0/5 | $0.0101 |
| qwen3-vl-flash (low) | 1 | 5 | 7 | 1.7/5 | $0.0051 |
| qwen3-vl-flash (none) | 0 | 2 | 0 | 2.0/5 | $0.0019 |
| qwen3-vl-plus (low) | 0 | 2 | 0 | 3.0/5 | $0.0209 |
| qwen3-vl-plus (medium) | 0 | 0 | 2 | 0.0/5 | $0.0304 |
| qwen3-vl-plus (none) | 0 | 2 | 0 | 2.0/5 | $0.0084 |
| qwen3.5-plus (low) | 0 | 2 | 0 | 2.0/5 | $0.0176 |
| qwen3.5-plus (medium) | 0 | 2 | 0 | 2.0/5 | $0.0177 |
| qwen3.5-plus (none) | 0 | 2 | 0 | 2.0/5 | $0.0164 |

### By Category

**invitations**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 0 | 11 | 3.2/5 |
| claude-sonnet-4-6 (low) | 7 | 4 | 4.3/5 |
| claude-sonnet-4-6 (none) | 7 | 4 | 4.4/5 |
| gemini-3-flash-preview (low) | 0 | 22 | 1.5/5 |
| gemini-3-flash-preview (medium) | 0 | 11 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 11 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 10 | 0.4/5 |
| gpt-4o-mini (low) | 0 | 11 | 4.0/5 |
| gpt-5-mini (low) | 6 | 5 | 4.0/5 |
| gpt-5-mini (medium) | 6 | 5 | 4.0/5 |
| gpt-5-nano (low) | 3 | 19 | 3.6/5 |
| gpt-5-nano (medium) | 5 | 6 | 3.8/5 |
| gpt-5.2 (low) | 4 | 7 | 3.6/5 |
| gpt-5.2 (medium) | 6 | 5 | 4.0/5 |
| kimi-k2.5 (low) | 0 | 10 | 0.0/5 |
| qwen3-vl-flash (low) | 0 | 10 | 4.0/5 |

**appointments**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 2 | 6 | 4.2/5 |
| claude-sonnet-4-6 (low) | 2 | 6 | 3.5/5 |
| claude-sonnet-4-6 (none) | 2 | 6 | 3.5/5 |
| gemini-3-flash-preview (low) | 0 | 16 | 2.0/5 |
| gemini-3-flash-preview (medium) | 0 | 8 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 8 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 8 | 0.0/5 |
| gpt-4o-mini (low) | 0 | 7 | 4.0/5 |
| gpt-5-mini (low) | 2 | 6 | 3.5/5 |
| gpt-5-mini (medium) | 3 | 5 | 3.8/5 |
| gpt-5-nano (low) | 0 | 16 | 3.5/5 |
| gpt-5-nano (medium) | 0 | 8 | 3.0/5 |
| gpt-5.2 (low) | 1 | 7 | 3.2/5 |
| gpt-5.2 (medium) | 1 | 7 | 3.2/5 |
| kimi-k2.5 (low) | 0 | 8 | 0.0/5 |
| qwen3-vl-flash (low) | 0 | 8 | 4.0/5 |

**meetings**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| MiniMax-M2.5 (none) | 0 | 1 | 0.0/5 |
| claude-haiku-4-5-20251001 (low) | 0 | 10 | 3.4/5 |
| claude-haiku-4-5-20251001 (none) | 0 | 1 | 3.0/5 |
| claude-sonnet-4-6 (low) | 1 | 9 | 3.0/5 |
| claude-sonnet-4-6 (none) | 1 | 9 | 3.0/5 |
| deepseek-chat (none) | 0 | 1 | 0.0/5 |
| gemini-3-flash-preview (low) | 0 | 20 | 1.9/5 |
| gemini-3-flash-preview (medium) | 0 | 10 | 0.3/5 |
| gemini-3-flash-preview (none) | 0 | 10 | 0.3/5 |
| glm-4.6v-flash (low) | 0 | 10 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 1 | 0.0/5 |
| gpt-5-mini (low) | 1 | 9 | 3.0/5 |
| gpt-5-mini (medium) | 0 | 10 | 2.8/5 |
| gpt-5-nano (low) | 1 | 19 | 3.4/5 |
| gpt-5-nano (medium) | 2 | 8 | 3.2/5 |
| gpt-5.2 (low) | 2 | 8 | 3.0/5 |
| gpt-5.2 (medium) | 1 | 9 | 2.8/5 |
| kimi-k2.5 (low) | 0 | 10 | 0.0/5 |
| kimi-k2.5 (none) | 0 | 1 | 0.0/5 |
| qwen-vl-max (none) | 0 | 1 | 3.0/5 |
| qwen3-vl-flash (low) | 0 | 10 | 3.6/5 |
| qwen3-vl-flash (none) | 0 | 1 | 3.0/5 |
| qwen3-vl-plus (low) | 0 | 1 | 3.0/5 |
| qwen3-vl-plus (medium) | 0 | 1 | 0.0/5 |
| qwen3-vl-plus (none) | 0 | 1 | 3.0/5 |
| qwen3.5-plus (low) | 0 | 1 | 3.0/5 |
| qwen3.5-plus (medium) | 0 | 1 | 1.0/5 |
| qwen3.5-plus (none) | 0 | 1 | 1.0/5 |

**travel**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 0 | 6 | 3.5/5 |
| claude-sonnet-4-6 (low) | 2 | 4 | 3.7/5 |
| claude-sonnet-4-6 (none) | 1 | 5 | 3.3/5 |
| gemini-3-flash-preview (low) | 0 | 12 | 1.8/5 |
| gemini-3-flash-preview (medium) | 0 | 6 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 6 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 6 | 0.0/5 |
| gpt-5-mini (low) | 0 | 6 | 2.7/5 |
| gpt-5-mini (medium) | 0 | 6 | 2.8/5 |
| gpt-5-nano (low) | 0 | 11 | 3.3/5 |
| gpt-5-nano (medium) | 0 | 6 | 2.8/5 |
| gpt-5.2 (low) | 1 | 5 | 3.2/5 |
| gpt-5.2 (medium) | 0 | 6 | 2.7/5 |
| kimi-k2.5 (low) | 0 | 6 | 0.0/5 |
| qwen3-vl-flash (low) | 0 | 6 | 3.7/5 |

**conferences**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 1 | 6 | 3.4/5 |
| claude-sonnet-4-6 (low) | 2 | 5 | 3.1/5 |
| claude-sonnet-4-6 (none) | 2 | 5 | 3.1/5 |
| gemini-3-flash-preview (low) | 0 | 14 | 1.6/5 |
| gemini-3-flash-preview (medium) | 0 | 7 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 7 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 7 | 0.6/5 |
| gpt-5-mini (low) | 1 | 6 | 2.7/5 |
| gpt-5-mini (medium) | 1 | 6 | 2.9/5 |
| gpt-5-nano (low) | 1 | 6 | 2.9/5 |
| gpt-5-nano (medium) | 0 | 7 | 2.6/5 |
| gpt-5.2 (low) | 1 | 6 | 2.6/5 |
| gpt-5.2 (medium) | 0 | 7 | 2.3/5 |
| kimi-k2.5 (low) | 0 | 7 | 0.0/5 |
| qwen3-vl-flash (low) | 0 | 7 | 3.3/5 |

**school**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 3 | 11 | 2.8/5 |
| claude-haiku-4-5-20251001 (none) | 0 | 2 | 3.0/5 |
| claude-sonnet-4-6 (low) | 3 | 3 | 4.0/5 |
| claude-sonnet-4-6 (none) | 5 | 9 | 3.6/5 |
| gemini-3-flash-preview (low) | 0 | 28 | 2.0/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.4/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.4/5 |
| glm-4.6v-flash (low) | 0 | 14 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 2 | 0.0/5 |
| gpt-5-mini (low) | 2 | 12 | 3.0/5 |
| gpt-5-mini (medium) | 2 | 12 | 3.1/5 |
| gpt-5-nano (low) | 2 | 12 | 2.9/5 |
| gpt-5-nano (medium) | 4 | 10 | 3.4/5 |
| gpt-5.2 (low) | 2 | 12 | 2.9/5 |
| gpt-5.2 (medium) | 2 | 12 | 3.1/5 |
| kimi-k2.5 (low) | 0 | 14 | 0.0/5 |
| kimi-k2.5 (none) | 0 | 2 | 4.0/5 |
| qwen-vl-max (none) | 0 | 2 | 2.0/5 |
| qwen3-vl-flash (low) | 0 | 14 | 2.6/5 |
| qwen3-vl-flash (none) | 0 | 2 | 2.0/5 |
| qwen3-vl-plus (low) | 0 | 2 | 3.0/5 |
| qwen3-vl-plus (medium) | 0 | 2 | 0.0/5 |
| qwen3-vl-plus (none) | 0 | 2 | 2.0/5 |
| qwen3.5-plus (low) | 0 | 2 | 2.0/5 |
| qwen3.5-plus (medium) | 0 | 2 | 2.0/5 |
| qwen3.5-plus (none) | 0 | 2 | 2.0/5 |

**recurring**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 0 | 4 | 3.2/5 |
| claude-sonnet-4-6 (none) | 2 | 2 | 3.8/5 |
| gemini-3-flash-preview (low) | 0 | 8 | 1.6/5 |
| gemini-3-flash-preview (medium) | 0 | 4 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 4 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 4 | 0.0/5 |
| gpt-5-mini (low) | 1 | 3 | 3.5/5 |
| gpt-5-mini (medium) | 2 | 2 | 4.0/5 |
| gpt-5-nano (low) | 2 | 2 | 3.8/5 |
| gpt-5-nano (medium) | 2 | 2 | 4.0/5 |
| gpt-5.2 (low) | 0 | 4 | 2.5/5 |
| gpt-5.2 (medium) | 0 | 4 | 2.8/5 |
| kimi-k2.5 (low) | 0 | 4 | 0.0/5 |
| qwen3-vl-flash (low) | 0 | 4 | 3.8/5 |

**no_events**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 7 | 7 | 2.9/5 |
| claude-sonnet-4-6 (none) | 13 | 1 | 4.7/5 |
| gemini-3-flash-preview (low) | 9 | 19 | 1.8/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.0/5 |
| glm-4.6v-flash (low) | 9 | 5 | 3.2/5 |
| gpt-5-mini (low) | 11 | 3 | 4.1/5 |
| gpt-5-mini (medium) | 12 | 2 | 4.4/5 |
| gpt-5-nano (low) | 8 | 6 | 3.3/5 |
| gpt-5-nano (medium) | 8 | 6 | 3.3/5 |
| gpt-5.2 (low) | 12 | 2 | 4.4/5 |
| gpt-5.2 (medium) | 11 | 3 | 4.1/5 |
| kimi-k2.5 (low) | 0 | 14 | 0.0/5 |
| qwen3-vl-flash (low) | 8 | 6 | 3.1/5 |

## Compare (Dedup) Results

| Model | Correct | Wrong | Accuracy | Cost |
|-------|---------|-------|----------|------|
| claude-haiku-4-5-20251001 (low) | 15 | 0 | 100.0% | $0.0144 |
| claude-sonnet-4-6 (none) | 15 | 0 | 100.0% | $0.0500 |
| gemini-3-flash-preview (low) | 12 | 18 | 40.0% | $0.0013 |
| gemini-3-flash-preview (medium) | 13 | 2 | 86.7% | $0.0013 |
| gemini-3-flash-preview (none) | 13 | 2 | 86.7% | $0.0014 |
| glm-4.6v-flash (low) | 0 | 15 | 0.0% | $0.0000 |
| gpt-5-mini (low) | 15 | 0 | 100.0% | $0.0055 |
| gpt-5-mini (medium) | 15 | 0 | 100.0% | $0.0098 |
| gpt-5-nano (low) | 15 | 0 | 100.0% | $0.0025 |
| gpt-5-nano (medium) | 14 | 1 | 93.3% | $0.0087 |
| gpt-5.2 (low) | 15 | 0 | 100.0% | $0.0302 |
| gpt-5.2 (medium) | 15 | 0 | 100.0% | $0.0325 |
| kimi-k2.5 (low) | 14 | 1 | 93.3% | $0.0375 |
| qwen3-vl-flash (low) | 15 | 0 | 100.0% | $0.0017 |

## Merge Results

| Model | Avg Rating | Pass (5/5) | Cost |
|-------|------------|------------|------|
| claude-haiku-4-5-20251001 (low) | 5.0/5 | 15/15 | $0.0158 |
| claude-sonnet-4-6 (none) | 5.0/5 | 15/15 | $0.0595 |
| gemini-3-flash-preview (low) | 0.0/5 | 0/30 | $0.0000 |
| gemini-3-flash-preview (medium) | 0.0/5 | 0/15 | $0.0000 |
| gemini-3-flash-preview (none) | 0.0/5 | 0/15 | $0.0000 |
| glm-4.6v-flash (low) | 0.3/5 | 1/15 | $0.0000 |
| gpt-5-mini (low) | 5.0/5 | 15/15 | $0.0089 |
| gpt-5-mini (medium) | 5.0/5 | 15/15 | $0.0142 |
| gpt-5-nano (low) | 4.9/5 | 13/15 | $0.0045 |
| gpt-5-nano (medium) | 5.0/5 | 15/15 | $0.0106 |
| gpt-5.2 (low) | 5.0/5 | 15/15 | $0.0356 |
| gpt-5.2 (medium) | 5.0/5 | 15/15 | $0.0406 |
| kimi-k2.5 (low) | 4.2/5 | 9/15 | $0.0565 |
| qwen3-vl-flash (low) | 5.0/5 | 15/15 | $0.0020 |

## Failure Patterns

| Tag | Total | Fail | Partial | Failure Rate |
|-----|-------|------|---------|--------------|
| car | 35 | 13 | 22 | 100% |
| service | 36 | 10 | 26 | 100% |
| auto | 18 | 5 | 13 | 100% |
| morning | 18 | 5 | 13 | 100% |
| dental | 18 | 5 | 13 | 100% |
| cleaning | 18 | 5 | 13 | 100% |
| reminder | 18 | 5 | 13 | 100% |
| home | 18 | 5 | 13 | 100% |
| repair | 18 | 5 | 13 | 100% |
| time-window | 18 | 5 | 13 | 100% |
| vet | 17 | 5 | 12 | 100% |
| pet | 17 | 5 | 12 | 100% |
| animal | 17 | 5 | 12 | 100% |
| attachment | 66 | 42 | 24 | 100% |
| markdown | 16 | 16 | 0 | 100% |
| csv | 16 | 5 | 11 | 100% |
| schedule | 16 | 5 | 11 | 100% |
| multiple-events | 49 | 19 | 30 | 100% |
| summit | 16 | 13 | 3 | 100% |
| multiple-sessions | 16 | 13 | 3 | 100% |
| webinar | 16 | 5 | 11 | 100% |
| online | 16 | 5 | 11 | 100% |
| baby-shower | 18 | 5 | 13 | 100% |
| brunch | 18 | 5 | 13 | 100% |
| weekend | 18 | 5 | 13 | 100% |
| retirement | 18 | 5 | 13 | 100% |
| lunch | 18 | 5 | 13 | 100% |
| celebration | 18 | 5 | 13 | 100% |
| multi-event | 30 | 22 | 8 | 100% |
| community | 30 | 19 | 11 | 100% |
| all-hands | 17 | 5 | 12 | 100% |
| company | 17 | 5 | 12 | 100% |
| announcement | 17 | 5 | 12 | 100% |
| town-hall | 17 | 5 | 12 | 100% |
| board | 17 | 4 | 13 | 100% |
| executive | 17 | 4 | 13 | 100% |
| client | 17 | 7 | 10 | 100% |
| call | 17 | 7 | 10 | 100% |
| meeting | 49 | 26 | 23 | 100% |
| ics | 17 | 16 | 1 | 100% |
| txt | 17 | 5 | 12 | 100% |
| annual | 17 | 7 | 10 | 100% |
| standup | 17 | 5 | 12 | 100% |
| team | 32 | 10 | 22 | 100% |
| daily | 17 | 5 | 12 | 100% |
| time-change | 17 | 5 | 12 | 100% |
| biweekly | 15 | 8 | 7 | 100% |
| weekly | 15 | 5 | 10 | 100% |
| multi-attachment | 15 | 10 | 5 | 100% |
| forwarded | 15 | 7 | 8 | 100% |
| borderline | 15 | 9 | 6 | 100% |
| digest | 41 | 35 | 6 | 100% |
| author-visit | 26 | 23 | 3 | 100% |
| play | 16 | 7 | 9 | 100% |
| arts | 16 | 7 | 9 | 100% |
| multiple-shows | 16 | 7 | 9 | 100% |
| transfer | 17 | 5 | 12 | 100% |
| shuttle | 17 | 5 | 12 | 100% |
| airport | 17 | 5 | 12 | 100% |
| pickup | 34 | 13 | 21 | 100% |
| rental | 17 | 8 | 9 | 100% |
| dropoff | 17 | 8 | 9 | 100% |
| flight | 17 | 5 | 12 | 100% |
| airline | 17 | 5 | 12 | 100% |
| itinerary | 16 | 9 | 7 | 100% |
| calendar | 73 | 44 | 28 | 99% |
| daycare | 71 | 33 | 37 | 99% |
| performance | 48 | 26 | 21 | 98% |
| 1:1 | 45 | 17 | 27 | 98% |
| manager | 45 | 17 | 27 | 98% |
| hr | 34 | 12 | 21 | 97% |
| multi-day | 64 | 45 | 17 | 97% |
| calendar-invite | 30 | 9 | 20 | 97% |
| salon | 18 | 5 | 12 | 94% |
| haircut | 18 | 5 | 12 | 94% |
| personal-care | 18 | 5 | 12 | 94% |
| interview | 17 | 5 | 11 | 94% |
| job | 17 | 5 | 11 | 94% |
| hiring | 17 | 5 | 11 | 94% |
| train | 17 | 5 | 11 | 94% |
| amtrak | 17 | 5 | 11 | 94% |
| corporate | 16 | 7 | 8 | 94% |
| mandatory | 16 | 7 | 8 | 94% |
| registration | 31 | 16 | 13 | 94% |
| extracurricular | 15 | 12 | 2 | 93% |
| booking | 51 | 16 | 31 | 92% |
| pdf | 86 | 50 | 29 | 92% |
| lawyer | 18 | 5 | 11 | 89% |
| consultation | 18 | 5 | 11 | 89% |
| housewarming | 18 | 5 | 11 | 89% |
| open-house | 18 | 5 | 11 | 89% |
| real-world | 233 | 141 | 64 | 88% |
| public-hearing | 16 | 6 | 8 | 88% |
| sports | 16 | 5 | 9 | 88% |
| soccer | 16 | 5 | 9 | 88% |
| game | 16 | 5 | 9 | 88% |
| training | 48 | 17 | 24 | 85% |
| recurring | 60 | 25 | 26 | 85% |
| newsletter | 71 | 49 | 11 | 85% |
| quarterly | 32 | 11 | 16 | 84% |
| review | 32 | 14 | 13 | 84% |
| doctor | 18 | 5 | 10 | 83% |
| confirmation | 18 | 5 | 10 | 83% |
| hotel | 17 | 6 | 8 | 82% |
| checkin | 17 | 6 | 8 | 82% |
| checkout | 17 | 6 | 8 | 82% |
| images | 117 | 76 | 20 | 82% |
| ceremony | 16 | 8 | 5 | 81% |
| government | 31 | 17 | 8 | 81% |
| casual | 36 | 10 | 19 | 81% |
| kickoff | 34 | 12 | 15 | 79% |
| project | 34 | 12 | 15 | 79% |
| adult | 18 | 5 | 9 | 78% |
| restaurant | 18 | 5 | 9 | 78% |
| formal | 69 | 21 | 32 | 77% |
| school | 267 | 126 | 79 | 77% |
| graduation | 34 | 13 | 13 | 76% |
| internal | 33 | 12 | 13 | 76% |
| holiday | 33 | 9 | 16 | 76% |
| city | 15 | 11 | 0 | 73% |
| public-comment | 15 | 11 | 0 | 73% |
| monthly | 15 | 5 | 6 | 73% |
| book-club | 15 | 5 | 6 | 73% |
| tech | 47 | 16 | 18 | 72% |
| virtual | 47 | 18 | 16 | 72% |
| dinner | 18 | 5 | 8 | 72% |
| friends | 18 | 5 | 8 | 72% |
| party | 18 | 5 | 8 | 72% |
| multi-part | 18 | 5 | 8 | 72% |
| all-day | 18 | 5 | 8 | 72% |
| legal | 33 | 12 | 11 | 70% |
| evening | 54 | 14 | 23 | 69% |
| afternoon | 36 | 10 | 14 | 67% |
| no_events | 15 | 10 | 0 | 67% |
| business | 15 | 7 | 3 | 67% |
| kids | 50 | 15 | 18 | 66% |
| workshop | 16 | 5 | 5 | 62% |
| in-person | 16 | 5 | 5 | 62% |
| accountant | 18 | 5 | 6 | 61% |
| tax | 18 | 5 | 6 | 61% |
| cpa | 18 | 5 | 6 | 61% |
| engagement | 18 | 5 | 6 | 61% |
| winery | 18 | 5 | 6 | 61% |
| outdoor | 18 | 5 | 6 | 61% |
| offer | 15 | 9 | 0 | 60% |
| deadline | 15 | 9 | 0 | 60% |
| tricky | 15 | 9 | 0 | 60% |
| survey | 15 | 9 | 0 | 60% |
| feedback | 15 | 9 | 0 | 60% |
| customer-service | 15 | 9 | 0 | 60% |
| planning | 17 | 5 | 5 | 59% |
| financial | 48 | 22 | 6 | 58% |
| professional | 49 | 12 | 16 | 57% |
| work | 60 | 14 | 20 | 57% |
| field-trip | 16 | 5 | 4 | 56% |
| permission | 16 | 5 | 4 | 56% |
| time-range | 18 | 5 | 5 | 56% |
| venue | 18 | 5 | 5 | 56% |
| office | 18 | 4 | 6 | 56% |
| medical | 65 | 14 | 22 | 55% |
| conference | 78 | 33 | 9 | 54% |
| promo | 30 | 16 | 0 | 53% |
| retail | 15 | 8 | 0 | 53% |
| shipping | 15 | 8 | 0 | 53% |
| delivery | 15 | 8 | 0 | 53% |
| tracking | 15 | 8 | 0 | 53% |
| agenda | 32 | 5 | 12 | 53% |
| complex | 31 | 9 | 7 | 52% |
| negative-test | 210 | 102 | 0 | 49% |
| bank | 15 | 7 | 0 | 47% |
| statement | 15 | 7 | 0 | 47% |
| marketing | 15 | 7 | 0 | 47% |
| sale | 15 | 7 | 0 | 47% |
| promotional | 15 | 7 | 0 | 47% |
| mall | 15 | 7 | 0 | 47% |
| terms | 15 | 7 | 0 | 47% |
| policy | 15 | 7 | 0 | 47% |
| birthday | 66 | 15 | 14 | 44% |
| parent-teacher | 16 | 5 | 2 | 44% |
| education | 16 | 5 | 2 | 44% |
| order | 30 | 13 | 0 | 43% |
| receipt | 30 | 13 | 0 | 43% |
| wedding | 33 | 5 | 9 | 42% |
| shopping | 30 | 12 | 0 | 40% |
| security | 15 | 6 | 0 | 40% |
| password | 15 | 6 | 0 | 40% |
| account | 15 | 6 | 0 | 40% |
| social | 60 | 11 | 7 | 30% |
| notification | 15 | 4 | 0 | 27% |
| linkedin | 15 | 4 | 0 | 27% |
| no-match | 105 | 19 | 0 | 18% |
| dedup | 225 | 39 | 0 | 17% |
| different-event | 30 | 5 | 0 | 17% |
| match | 120 | 20 | 0 | 17% |
| travel | 30 | 3 | 1 | 13% |
| different-date | 15 | 2 | 0 | 13% |
| modality-change | 15 | 0 | 2 | 13% |
| duration-change | 15 | 0 | 1 | 7% |
| time-update | 30 | 0 | 2 | 7% |
| location-update | 30 | 0 | 2 | 7% |
| logistics | 30 | 0 | 2 | 7% |
| dress-code | 15 | 0 | 1 | 7% |
| description-enrichment | 105 | 0 | 4 | 4% |
| merge | 225 | 0 | 8 | 4% |
| reschedule | 30 | 0 | 1 | 3% |

## Cost Analysis

### Per-Eval Cost

| Model | Extract Avg | Compare Avg | Merge Avg | Total |
|-------|-------------|-------------|-----------|-------|
| MiniMax-M2.5 (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| claude-haiku-4-5-20251001 (low) | $0.002570 | $0.000963 | $0.001051 | $0.2204 |
| claude-haiku-4-5-20251001 (none) | $0.004883 | $0.000000 | $0.000000 | $0.0146 |
| claude-sonnet-4-6 (low) | $0.008825 | $0.000000 | $0.000000 | $0.4236 |
| claude-sonnet-4-6 (none) | $0.012128 | $0.003331 | $0.003966 | $1.0069 |
| deepseek-chat (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gemini-3-flash-preview (low) | $0.000253 | $0.000045 | $0.000000 | $0.0388 |
| gemini-3-flash-preview (medium) | $0.000035 | $0.000090 | $0.000000 | $0.0039 |
| gemini-3-flash-preview (none) | $0.000033 | $0.000092 | $0.000000 | $0.0038 |
| glm-4.6v-flash (low) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| glm-4.6v-flash (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gpt-4o-mini (low) | $0.000243 | $0.000000 | $0.000000 | $0.0044 |
| gpt-5-mini (low) | $0.001577 | $0.000366 | $0.000591 | $0.1310 |
| gpt-5-mini (medium) | $0.002711 | $0.000655 | $0.000947 | $0.2247 |
| gpt-5-nano (low) | $0.000639 | $0.000168 | $0.000298 | $0.0760 |
| gpt-5-nano (medium) | $0.001293 | $0.000578 | $0.000709 | $0.1150 |
| gpt-5.2 (low) | $0.008188 | $0.002013 | $0.002376 | $0.6718 |
| gpt-5.2 (medium) | $0.010641 | $0.002168 | $0.002708 | $0.8605 |
| kimi-k2.5 (low) | $0.000000 | $0.002498 | $0.003770 | $0.0940 |
| kimi-k2.5 (none) | $0.007306 | $0.000000 | $0.000000 | $0.0219 |
| qwen-vl-max (none) | $0.003940 | $0.000000 | $0.000000 | $0.0118 |
| qwen3-vl-flash (low) | $0.000309 | $0.000110 | $0.000133 | $0.0262 |
| qwen3-vl-flash (none) | $0.000707 | $0.000000 | $0.000000 | $0.0021 |
| qwen3-vl-plus (low) | $0.009529 | $0.000000 | $0.000000 | $0.0286 |
| qwen3-vl-plus (medium) | $0.015113 | $0.000000 | $0.000000 | $0.0453 |
| qwen3-vl-plus (none) | $0.003175 | $0.000000 | $0.000000 | $0.0095 |
| qwen3.5-plus (low) | $0.011063 | $0.000000 | $0.000000 | $0.0332 |
| qwen3.5-plus (medium) | $0.012595 | $0.000000 | $0.000000 | $0.0378 |
| qwen3.5-plus (none) | $0.005877 | $0.000000 | $0.000000 | $0.0176 |

### Monthly Cost Projection

Assumptions per tier:
- **Tier 1 (50 emails)**: 50 emails/month, 10% with images, 40% trigger dedup, 20% trigger merge
- **Tier 2 (150 emails)**: 150 emails/month, 15% with images, 50% trigger dedup, 25% trigger merge
- **Tier 3 (500 emails)**: 500 emails/month, 20% with images, 60% trigger dedup, 30% trigger merge

| Model | Tier 1 (50 emails) | Tier 2 (150 emails) | Tier 3 (500 emails) |
|-------|--------------------|--------------------|--------------------|
| MiniMax-M2.5 (none) | $0.00 | $0.00 | $0.00 |
| claude-haiku-4-5-20251001 (low) | $0.16 | $0.50 | $1.73 |
| claude-haiku-4-5-20251001 (none) | $0.24 | $0.73 | $2.44 |
| claude-sonnet-4-6 (low) | $0.44 | $1.32 | $4.41 |
| claude-sonnet-4-6 (none) | $0.71 | $2.22 | $7.66 |
| deepseek-chat (none) | $0.00 | $0.00 | $0.00 |
| gemini-3-flash-preview (low) | $0.01 | $0.04 | $0.14 |
| gemini-3-flash-preview (medium) | $0.00 | $0.01 | $0.04 |
| gemini-3-flash-preview (none) | $0.00 | $0.01 | $0.04 |
| glm-4.6v-flash (low) | $0.00 | $0.00 | $0.00 |
| glm-4.6v-flash (none) | $0.00 | $0.00 | $0.00 |
| gpt-4o-mini (low) | $0.01 | $0.04 | $0.12 |
| gpt-5-mini (low) | $0.09 | $0.29 | $0.99 |
| gpt-5-mini (medium) | $0.16 | $0.49 | $1.69 |
| gpt-5-nano (low) | $0.04 | $0.12 | $0.41 |
| gpt-5-nano (medium) | $0.08 | $0.26 | $0.93 |
| gpt-5.2 (low) | $0.47 | $1.47 | $5.05 |
| gpt-5.2 (medium) | $0.60 | $1.86 | $6.38 |
| kimi-k2.5 (low) | $0.09 | $0.33 | $1.31 |
| kimi-k2.5 (none) | $0.37 | $1.10 | $3.65 |
| qwen-vl-max (none) | $0.20 | $0.59 | $1.97 |
| qwen3-vl-flash (low) | $0.02 | $0.06 | $0.21 |
| qwen3-vl-flash (none) | $0.04 | $0.11 | $0.35 |
| qwen3-vl-plus (low) | $0.48 | $1.43 | $4.76 |
| qwen3-vl-plus (medium) | $0.76 | $2.27 | $7.56 |
| qwen3-vl-plus (none) | $0.16 | $0.48 | $1.59 |
| qwen3.5-plus (low) | $0.55 | $1.66 | $5.53 |
| qwen3.5-plus (medium) | $0.63 | $1.89 | $6.30 |
| qwen3.5-plus (none) | $0.29 | $0.88 | $2.94 |

## Token Usage

| Model | Avg Prompt Tokens | Avg Completion Tokens | Total Tokens |
|-------|-------------------|----------------------|--------------|
| MiniMax-M2.5 (none) | 0 | 0 | 0 |
| claude-haiku-4-5-20251001 (low) | 1377 | 254 | 169649 |
| claude-haiku-4-5-20251001 (none) | 3141 | 593 | 11200 |
| claude-sonnet-4-6 (low) | 1810 | 226 | 97732 |
| claude-sonnet-4-6 (none) | 1764 | 293 | 213931 |
| deepseek-chat (none) | 0 | 0 | 0 |
| gemini-3-flash-preview (low) | 798 | 111 | 189046 |
| gemini-3-flash-preview (medium) | 137 | 28 | 17201 |
| gemini-3-flash-preview (none) | 138 | 27 | 17068 |
| glm-4.6v-flash (low) | 754 | 1058 | 186640 |
| glm-4.6v-flash (none) | 3551 | 2120 | 17011 |
| gpt-4o-mini (low) | 1007 | 153 | 20887 |
| gpt-5-mini (low) | 1330 | 464 | 186521 |
| gpt-5-mini (medium) | 1330 | 914 | 233337 |
| gpt-5-nano (low) | 1310 | 1214 | 348216 |
| gpt-5-nano (medium) | 1413 | 2588 | 416056 |
| gpt-5.2 (low) | 1330 | 295 | 168988 |
| gpt-5.2 (medium) | 1330 | 425 | 182473 |
| kimi-k2.5 (low) | 106 | 283 | 40081 |
| kimi-k2.5 (none) | 2907 | 1854 | 14283 |
| qwen-vl-max (none) | 2565 | 590 | 9466 |
| qwen3-vl-flash (low) | 1099 | 245 | 138449 |
| qwen3-vl-flash (none) | 3240 | 659 | 11698 |
| qwen3-vl-plus (low) | 3235 | 2573 | 17426 |
| qwen3-vl-plus (medium) | 3235 | 4318 | 22661 |
| qwen3-vl-plus (none) | 3240 | 587 | 11482 |
| qwen3.5-plus (low) | 3282 | 1318 | 13802 |
| qwen3.5-plus (medium) | 3282 | 1558 | 14520 |
| qwen3.5-plus (none) | 3285 | 508 | 11378 |

## Regression Analysis

Multiple code versions detected — showing latest vs previous where applicable.


