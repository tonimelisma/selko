# Selko LLM Eval Report
Generated: 2026-02-21T22:38:13.507417+00:00

## Eval Run Overview

| Metric | Value |
|--------|-------|
| **Total Eval Cost** | **$4.2943** |
| Total Evals | 1779 (1299 extract, 240 compare, 240 merge) |
| Models Tested | 29 |
| Total Tokens | 3,314,221 |
| Total API Time | 15462s |
| Code Hash | 274b820b8ecc, 2bf536dc0a22, 4dece2183c36, 6e8b4c59aa00, unknown |

## Model Comparison

| Model | Extract | Compare | Merge | Cost | Avg Latency |
|-------|---------|---------|-------|------|-------------|
| MiniMax-M2.5 (none) | 0/1 (0.0%) | - | - | $0.0000 | 11423ms |
| claude-haiku-4-5-20251001 (low) | 13/73 (17.8%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2192 | 2563ms |
| claude-haiku-4-5-20251001 (none) | 0/3 (0.0%) | - | - | $0.0146 | 4734ms |
| claude-sonnet-4-6 (low) | 17/47 (36.2%) | - | - | $0.4186 | 3656ms |
| claude-sonnet-4-6 (none) | 33/73 (45.2%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $1.0019 | 4630ms |
| deepseek-chat (none) | 0/1 (0.0%) | - | - | $0.0000 | 6276ms |
| gemini-3-flash-preview (low) | 72/146 (49.3%) | 15/30 (50.0%) | 14/30 (2.3 avg) | $0.0732 | 8704ms |
| gemini-3-flash-preview (medium) | 0/73 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0039 | 3454ms |
| gemini-3-flash-preview (none) | 0/73 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0038 | 2793ms |
| glm-4.6v-flash (low) | 9/72 (12.5%) | 0/15 (0.0%) | 1/15 (0.3 avg) | $0.0000 | 14048ms |
| glm-4.6v-flash (none) | 0/3 (0.0%) | - | - | $0.0000 | 36190ms |
| gpt-4o-mini (low) | 0/18 (0.0%) | - | - | $0.0044 | 4150ms |
| gpt-5-mini (low) | 59/73 (80.8%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.1330 | 7660ms |
| gpt-5-mini (medium) | 26/73 (35.6%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2240 | 14359ms |
| gpt-5-nano (low) | 17/107 (15.9%) | 15/15 (100.0%) | 13/15 (4.9 avg) | $0.0760 | 10970ms |
| gpt-5-nano (medium) | 21/73 (28.8%) | 14/15 (93.3%) | 15/15 (5.0 avg) | $0.1145 | 21406ms |
| gpt-5.2 (low) | 23/73 (31.5%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.6693 | 5162ms |
| gpt-5.2 (medium) | 21/73 (28.8%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.8580 | 7499ms |
| kimi-k2.5 (low) | 0/72 (0.0%) | 14/15 (93.3%) | 9/15 (4.2 avg) | $0.0940 | 6634ms |
| kimi-k2.5 (none) | 0/3 (0.0%) | - | - | $0.0219 | 41939ms |
| qwen-vl-max (none) | 0/3 (0.0%) | - | - | $0.0118 | 21302ms |
| qwen3-vl-flash (low) | 61/145 (42.1%) | 30/30 (100.0%) | 30/30 (5.0 avg) | $0.1779 | 9028ms |
| qwen3-vl-flash (none) | 0/3 (0.0%) | - | - | $0.0021 | 8075ms |
| qwen3-vl-plus (low) | 0/3 (0.0%) | - | - | $0.0286 | 32654ms |
| qwen3-vl-plus (medium) | 0/3 (0.0%) | - | - | $0.0453 | 53943ms |
| qwen3-vl-plus (none) | 0/3 (0.0%) | - | - | $0.0095 | 10558ms |
| qwen3.5-plus (low) | 0/3 (0.0%) | - | - | $0.0332 | 18636ms |
| qwen3.5-plus (medium) | 0/3 (0.0%) | - | - | $0.0378 | 23866ms |
| qwen3.5-plus (none) | 0/3 (0.0%) | - | - | $0.0176 | 8327ms |
| **TOTAL** | | | | **$4.2943** | |

*Note: Models ran different numbers of extract fixtures (1, 3, 18, 47, 72, 73, 107, 145, 146). Text-only models skip vision fixtures (images, PDFs), so pass rates are not directly comparable.*

## Extraction Results

### All Fixtures

| Model | Pass | Partial | Fail | Avg Rating | Cost |
|-------|------|---------|------|------------|------|
| MiniMax-M2.5 (none) | 0 | 0 | 1 | 0.0/5 | $0.0000 |
| claude-haiku-4-5-20251001 (low) | 13 | 48 | 12 | 3.3/5 | $0.1890 |
| claude-haiku-4-5-20251001 (none) | 0 | 3 | 0 | 3.0/5 | $0.0146 |
| claude-sonnet-4-6 (low) | 17 | 29 | 1 | 3.7/5 | $0.4186 |
| claude-sonnet-4-6 (none) | 33 | 38 | 2 | 3.8/5 | $0.8925 |
| deepseek-chat (none) | 0 | 0 | 1 | 0.0/5 | $0.0000 |
| gemini-3-flash-preview (low) | 72 | 59 | 15 | 4.0/5 | $0.0696 |
| gemini-3-flash-preview (medium) | 0 | 3 | 70 | 0.1/5 | $0.0026 |
| gemini-3-flash-preview (none) | 0 | 3 | 70 | 0.1/5 | $0.0024 |
| glm-4.6v-flash (low) | 9 | 5 | 58 | 0.9/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 3 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 18 | 0 | 4.0/5 | $0.0044 |
| gpt-5-mini (low) | 59 | 10 | 4 | 4.6/5 | $0.1198 |
| gpt-5-mini (medium) | 26 | 44 | 3 | 3.5/5 | $0.1999 |
| gpt-5-nano (low) | 17 | 83 | 7 | 3.4/5 | $0.0689 |
| gpt-5-nano (medium) | 21 | 45 | 7 | 3.3/5 | $0.0952 |
| gpt-5.2 (low) | 23 | 47 | 3 | 3.3/5 | $0.6035 |
| gpt-5.2 (medium) | 21 | 48 | 4 | 3.3/5 | $0.7849 |
| kimi-k2.5 (low) | 0 | 0 | 72 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 1 | 2.7/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 3 | 0 | 2.3/5 | $0.0118 |
| qwen3-vl-flash (low) | 61 | 65 | 19 | 3.9/5 | $0.1417 |
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
| gemini-3-flash-preview (low) | 10 | 13 | 5 | 3.6/5 | $0.0413 |
| gemini-3-flash-preview (medium) | 0 | 2 | 12 | 0.4/5 | $0.0023 |
| gemini-3-flash-preview (none) | 0 | 2 | 12 | 0.4/5 | $0.0022 |
| glm-4.6v-flash (low) | 1 | 1 | 11 | 0.7/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 2 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 1 | 0 | 4.0/5 | $0.0006 |
| gpt-5-mini (low) | 7 | 6 | 1 | 4.1/5 | $0.0416 |
| gpt-5-mini (medium) | 2 | 10 | 2 | 2.8/5 | $0.0734 |
| gpt-5-nano (low) | 3 | 11 | 1 | 2.9/5 | $0.0109 |
| gpt-5-nano (medium) | 4 | 9 | 1 | 3.3/5 | $0.0282 |
| gpt-5.2 (low) | 3 | 10 | 1 | 2.9/5 | $0.2396 |
| gpt-5.2 (medium) | 3 | 10 | 1 | 3.1/5 | $0.3075 |
| kimi-k2.5 (low) | 0 | 0 | 13 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 0 | 4.0/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 2 | 0 | 2.0/5 | $0.0101 |
| qwen3-vl-flash (low) | 6 | 12 | 9 | 2.7/5 | $0.0329 |
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
| gemini-3-flash-preview (low) | 11 | 11 | 4.0/5 |
| gemini-3-flash-preview (medium) | 0 | 11 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 11 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 10 | 0.4/5 |
| gpt-4o-mini (low) | 0 | 11 | 4.0/5 |
| gpt-5-mini (low) | 10 | 1 | 4.7/5 |
| gpt-5-mini (medium) | 6 | 5 | 4.0/5 |
| gpt-5-nano (low) | 3 | 19 | 3.6/5 |
| gpt-5-nano (medium) | 5 | 6 | 3.8/5 |
| gpt-5.2 (low) | 4 | 7 | 3.6/5 |
| gpt-5.2 (medium) | 6 | 5 | 4.0/5 |
| kimi-k2.5 (low) | 0 | 10 | 0.0/5 |
| qwen3-vl-flash (low) | 10 | 11 | 4.3/5 |

**appointments**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 2 | 6 | 4.2/5 |
| claude-sonnet-4-6 (low) | 2 | 6 | 3.5/5 |
| claude-sonnet-4-6 (none) | 2 | 6 | 3.5/5 |
| gemini-3-flash-preview (low) | 8 | 8 | 4.0/5 |
| gemini-3-flash-preview (medium) | 0 | 8 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 8 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 8 | 0.0/5 |
| gpt-4o-mini (low) | 0 | 7 | 4.0/5 |
| gpt-5-mini (low) | 8 | 0 | 5.0/5 |
| gpt-5-mini (medium) | 3 | 5 | 3.8/5 |
| gpt-5-nano (low) | 0 | 16 | 3.5/5 |
| gpt-5-nano (medium) | 0 | 8 | 3.0/5 |
| gpt-5.2 (low) | 1 | 7 | 3.2/5 |
| gpt-5.2 (medium) | 1 | 7 | 3.2/5 |
| kimi-k2.5 (low) | 0 | 8 | 0.0/5 |
| qwen3-vl-flash (low) | 8 | 8 | 4.5/5 |

**meetings**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| MiniMax-M2.5 (none) | 0 | 1 | 0.0/5 |
| claude-haiku-4-5-20251001 (low) | 0 | 10 | 3.4/5 |
| claude-haiku-4-5-20251001 (none) | 0 | 1 | 3.0/5 |
| claude-sonnet-4-6 (low) | 1 | 9 | 3.0/5 |
| claude-sonnet-4-6 (none) | 1 | 9 | 3.0/5 |
| deepseek-chat (none) | 0 | 1 | 0.0/5 |
| gemini-3-flash-preview (low) | 9 | 11 | 4.0/5 |
| gemini-3-flash-preview (medium) | 0 | 10 | 0.3/5 |
| gemini-3-flash-preview (none) | 0 | 10 | 0.3/5 |
| glm-4.6v-flash (low) | 0 | 10 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 1 | 0.0/5 |
| gpt-5-mini (low) | 9 | 1 | 4.8/5 |
| gpt-5-mini (medium) | 0 | 10 | 2.8/5 |
| gpt-5-nano (low) | 1 | 19 | 3.4/5 |
| gpt-5-nano (medium) | 2 | 8 | 3.2/5 |
| gpt-5.2 (low) | 2 | 8 | 3.0/5 |
| gpt-5.2 (medium) | 1 | 9 | 2.8/5 |
| kimi-k2.5 (low) | 0 | 10 | 0.0/5 |
| kimi-k2.5 (none) | 0 | 1 | 0.0/5 |
| qwen-vl-max (none) | 0 | 1 | 3.0/5 |
| qwen3-vl-flash (low) | 8 | 12 | 4.2/5 |
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
| gemini-3-flash-preview (low) | 5 | 7 | 4.1/5 |
| gemini-3-flash-preview (medium) | 0 | 6 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 6 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 6 | 0.0/5 |
| gpt-5-mini (low) | 5 | 1 | 4.8/5 |
| gpt-5-mini (medium) | 0 | 6 | 2.8/5 |
| gpt-5-nano (low) | 0 | 11 | 3.3/5 |
| gpt-5-nano (medium) | 0 | 6 | 2.8/5 |
| gpt-5.2 (low) | 1 | 5 | 3.2/5 |
| gpt-5.2 (medium) | 0 | 6 | 2.7/5 |
| kimi-k2.5 (low) | 0 | 6 | 0.0/5 |
| qwen3-vl-flash (low) | 4 | 8 | 3.9/5 |

**conferences**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 1 | 5 | 3.8/5 |
| claude-sonnet-4-6 (low) | 2 | 4 | 3.5/5 |
| claude-sonnet-4-6 (none) | 2 | 4 | 3.5/5 |
| gemini-3-flash-preview (low) | 5 | 7 | 3.8/5 |
| gemini-3-flash-preview (medium) | 0 | 6 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 6 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 6 | 0.5/5 |
| gpt-5-mini (low) | 5 | 1 | 4.5/5 |
| gpt-5-mini (medium) | 1 | 5 | 3.2/5 |
| gpt-5-nano (low) | 1 | 5 | 3.2/5 |
| gpt-5-nano (medium) | 0 | 6 | 2.8/5 |
| gpt-5.2 (low) | 1 | 5 | 2.8/5 |
| gpt-5.2 (medium) | 0 | 6 | 2.5/5 |
| kimi-k2.5 (low) | 0 | 6 | 0.0/5 |
| qwen3-vl-flash (low) | 5 | 7 | 4.1/5 |

**school**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 3 | 11 | 2.8/5 |
| claude-haiku-4-5-20251001 (none) | 0 | 2 | 3.0/5 |
| claude-sonnet-4-6 (low) | 3 | 3 | 4.0/5 |
| claude-sonnet-4-6 (none) | 5 | 9 | 3.6/5 |
| gemini-3-flash-preview (low) | 10 | 18 | 4.1/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.4/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.4/5 |
| glm-4.6v-flash (low) | 0 | 14 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 2 | 0.0/5 |
| gpt-5-mini (low) | 8 | 6 | 4.5/5 |
| gpt-5-mini (medium) | 2 | 12 | 3.1/5 |
| gpt-5-nano (low) | 2 | 12 | 2.9/5 |
| gpt-5-nano (medium) | 4 | 10 | 3.4/5 |
| gpt-5.2 (low) | 2 | 12 | 2.9/5 |
| gpt-5.2 (medium) | 2 | 12 | 3.1/5 |
| kimi-k2.5 (low) | 0 | 14 | 0.0/5 |
| kimi-k2.5 (none) | 0 | 2 | 4.0/5 |
| qwen-vl-max (none) | 0 | 2 | 2.0/5 |
| qwen3-vl-flash (low) | 6 | 22 | 3.3/5 |
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
| gemini-3-flash-preview (low) | 4 | 4 | 3.8/5 |
| gemini-3-flash-preview (medium) | 0 | 4 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 4 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 4 | 0.0/5 |
| gpt-5-mini (low) | 4 | 0 | 5.0/5 |
| gpt-5-mini (medium) | 2 | 2 | 4.0/5 |
| gpt-5-nano (low) | 2 | 2 | 3.8/5 |
| gpt-5-nano (medium) | 2 | 2 | 4.0/5 |
| gpt-5.2 (low) | 0 | 4 | 2.5/5 |
| gpt-5.2 (medium) | 0 | 4 | 2.8/5 |
| kimi-k2.5 (low) | 0 | 4 | 0.0/5 |
| qwen3-vl-flash (low) | 3 | 5 | 4.2/5 |

**no_events**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 7 | 7 | 2.9/5 |
| claude-sonnet-4-6 (none) | 13 | 1 | 4.7/5 |
| gemini-3-flash-preview (low) | 20 | 8 | 3.9/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.0/5 |
| glm-4.6v-flash (low) | 9 | 5 | 3.2/5 |
| gpt-5-mini (low) | 10 | 4 | 3.9/5 |
| gpt-5-mini (medium) | 12 | 2 | 4.4/5 |
| gpt-5-nano (low) | 8 | 6 | 3.3/5 |
| gpt-5-nano (medium) | 8 | 6 | 3.3/5 |
| gpt-5.2 (low) | 12 | 2 | 4.4/5 |
| gpt-5.2 (medium) | 11 | 3 | 4.1/5 |
| kimi-k2.5 (low) | 0 | 14 | 0.0/5 |
| qwen3-vl-flash (low) | 17 | 11 | 3.3/5 |

## Compare (Dedup) Results

| Model | Correct | Wrong | Accuracy | Cost |
|-------|---------|-------|----------|------|
| claude-haiku-4-5-20251001 (low) | 15 | 0 | 100.0% | $0.0144 |
| claude-sonnet-4-6 (none) | 15 | 0 | 100.0% | $0.0500 |
| gemini-3-flash-preview (low) | 15 | 15 | 50.0% | $0.0017 |
| gemini-3-flash-preview (medium) | 13 | 2 | 86.7% | $0.0013 |
| gemini-3-flash-preview (none) | 13 | 2 | 86.7% | $0.0014 |
| glm-4.6v-flash (low) | 0 | 15 | 0.0% | $0.0000 |
| gpt-5-mini (low) | 15 | 0 | 100.0% | $0.0054 |
| gpt-5-mini (medium) | 15 | 0 | 100.0% | $0.0098 |
| gpt-5-nano (low) | 15 | 0 | 100.0% | $0.0025 |
| gpt-5-nano (medium) | 14 | 1 | 93.3% | $0.0087 |
| gpt-5.2 (low) | 15 | 0 | 100.0% | $0.0302 |
| gpt-5.2 (medium) | 15 | 0 | 100.0% | $0.0325 |
| kimi-k2.5 (low) | 14 | 1 | 93.3% | $0.0375 |
| qwen3-vl-flash (low) | 30 | 0 | 100.0% | $0.0153 |

## Merge Results

| Model | Avg Rating | Pass (5/5) | Cost |
|-------|------------|------------|------|
| claude-haiku-4-5-20251001 (low) | 5.0/5 | 15/15 | $0.0158 |
| claude-sonnet-4-6 (none) | 5.0/5 | 15/15 | $0.0595 |
| gemini-3-flash-preview (low) | 2.3/5 | 14/30 | $0.0019 |
| gemini-3-flash-preview (medium) | 0.0/5 | 0/15 | $0.0000 |
| gemini-3-flash-preview (none) | 0.0/5 | 0/15 | $0.0000 |
| glm-4.6v-flash (low) | 0.3/5 | 1/15 | $0.0000 |
| gpt-5-mini (low) | 5.0/5 | 15/15 | $0.0078 |
| gpt-5-mini (medium) | 5.0/5 | 15/15 | $0.0142 |
| gpt-5-nano (low) | 4.9/5 | 13/15 | $0.0045 |
| gpt-5-nano (medium) | 5.0/5 | 15/15 | $0.0106 |
| gpt-5.2 (low) | 5.0/5 | 15/15 | $0.0356 |
| gpt-5.2 (medium) | 5.0/5 | 15/15 | $0.0406 |
| kimi-k2.5 (low) | 4.2/5 | 9/15 | $0.0565 |
| qwen3-vl-flash (low) | 5.0/5 | 30/30 | $0.0210 |

## Failure Patterns

| Tag | Total | Fail | Partial | Failure Rate |
|-----|-------|------|---------|--------------|
| multi-attachment | 16 | 8 | 8 | 100% |
| digest | 43 | 31 | 12 | 100% |
| author-visit | 27 | 21 | 6 | 100% |
| txt | 18 | 4 | 13 | 94% |
| rental | 18 | 7 | 10 | 94% |
| dropoff | 18 | 7 | 10 | 94% |
| itinerary | 17 | 8 | 8 | 94% |
| multi-event | 32 | 19 | 11 | 94% |
| borderline | 16 | 8 | 7 | 94% |
| daycare | 75 | 28 | 40 | 91% |
| community | 32 | 17 | 12 | 91% |
| calendar | 77 | 38 | 31 | 90% |
| car | 37 | 12 | 21 | 89% |
| board | 18 | 3 | 13 | 89% |
| executive | 18 | 3 | 13 | 89% |
| annual | 18 | 6 | 10 | 89% |
| pickup | 36 | 11 | 21 | 89% |
| attachment | 53 | 22 | 25 | 89% |
| multiple-events | 52 | 16 | 30 | 88% |
| csv | 17 | 4 | 11 | 88% |
| schedule | 17 | 4 | 11 | 88% |
| summit | 17 | 12 | 3 | 88% |
| multiple-sessions | 17 | 12 | 3 | 88% |
| forwarded | 16 | 6 | 8 | 88% |
| extracurricular | 16 | 11 | 3 | 88% |
| calendar-invite | 31 | 9 | 18 | 87% |
| meeting | 52 | 22 | 23 | 87% |
| multi-day | 51 | 27 | 17 | 86% |
| performance | 51 | 23 | 21 | 86% |
| 1:1 | 47 | 16 | 24 | 85% |
| manager | 47 | 16 | 24 | 85% |
| registration | 33 | 15 | 13 | 85% |
| service | 38 | 9 | 23 | 84% |
| auto | 19 | 5 | 11 | 84% |
| morning | 19 | 5 | 11 | 84% |
| dental | 19 | 4 | 12 | 84% |
| cleaning | 19 | 4 | 12 | 84% |
| reminder | 19 | 4 | 12 | 84% |
| home | 19 | 4 | 12 | 84% |
| repair | 19 | 4 | 12 | 84% |
| time-window | 19 | 4 | 12 | 84% |
| baby-shower | 19 | 4 | 12 | 84% |
| brunch | 19 | 4 | 12 | 84% |
| weekend | 19 | 4 | 12 | 84% |
| retirement | 19 | 4 | 12 | 84% |
| lunch | 19 | 4 | 12 | 84% |
| celebration | 19 | 4 | 12 | 84% |
| pdf | 91 | 43 | 33 | 84% |
| vet | 18 | 4 | 11 | 83% |
| pet | 18 | 4 | 11 | 83% |
| animal | 18 | 4 | 11 | 83% |
| all-hands | 18 | 4 | 11 | 83% |
| company | 18 | 4 | 11 | 83% |
| announcement | 18 | 4 | 11 | 83% |
| town-hall | 18 | 4 | 11 | 83% |
| client | 18 | 7 | 8 | 83% |
| call | 18 | 7 | 8 | 83% |
| ics | 18 | 14 | 1 | 83% |
| hr | 36 | 10 | 20 | 83% |
| standup | 18 | 4 | 11 | 83% |
| daily | 18 | 4 | 11 | 83% |
| time-change | 18 | 4 | 11 | 83% |
| transfer | 18 | 4 | 11 | 83% |
| shuttle | 18 | 4 | 11 | 83% |
| airport | 18 | 4 | 11 | 83% |
| flight | 18 | 4 | 11 | 83% |
| airline | 18 | 4 | 11 | 83% |
| webinar | 17 | 4 | 10 | 82% |
| online | 17 | 4 | 10 | 82% |
| team | 34 | 8 | 20 | 82% |
| play | 17 | 6 | 8 | 82% |
| arts | 17 | 6 | 8 | 82% |
| multiple-shows | 17 | 6 | 8 | 82% |
| real-world | 247 | 127 | 74 | 81% |
| biweekly | 16 | 7 | 6 | 81% |
| weekly | 16 | 4 | 9 | 81% |
| newsletter | 75 | 43 | 17 | 80% |
| salon | 19 | 4 | 11 | 79% |
| haircut | 19 | 4 | 11 | 79% |
| personal-care | 19 | 4 | 11 | 79% |
| images | 124 | 71 | 26 | 78% |
| interview | 18 | 4 | 10 | 78% |
| job | 18 | 4 | 10 | 78% |
| hiring | 18 | 4 | 10 | 78% |
| train | 18 | 4 | 10 | 78% |
| amtrak | 18 | 4 | 10 | 78% |
| corporate | 17 | 6 | 7 | 76% |
| mandatory | 17 | 6 | 7 | 76% |
| quarterly | 34 | 10 | 16 | 76% |
| review | 34 | 13 | 13 | 76% |
| ceremony | 17 | 8 | 5 | 76% |
| booking | 54 | 13 | 28 | 76% |
| city | 16 | 12 | 0 | 75% |
| public-comment | 16 | 12 | 0 | 75% |
| doctor | 19 | 4 | 10 | 74% |
| confirmation | 19 | 4 | 10 | 74% |
| lawyer | 19 | 5 | 9 | 74% |
| consultation | 19 | 5 | 9 | 74% |
| housewarming | 19 | 4 | 10 | 74% |
| open-house | 19 | 4 | 10 | 74% |
| government | 33 | 17 | 7 | 73% |
| training | 51 | 14 | 23 | 73% |
| public-hearing | 17 | 5 | 7 | 71% |
| sports | 17 | 4 | 8 | 71% |
| soccer | 17 | 4 | 8 | 71% |
| game | 17 | 4 | 8 | 71% |
| recurring | 64 | 22 | 23 | 70% |
| school | 283 | 110 | 88 | 70% |
| graduation | 36 | 12 | 13 | 69% |
| formal | 73 | 18 | 32 | 68% |
| casual | 38 | 8 | 18 | 68% |
| kickoff | 36 | 11 | 13 | 67% |
| project | 36 | 11 | 13 | 67% |
| hotel | 18 | 5 | 7 | 67% |
| checkin | 18 | 5 | 7 | 67% |
| checkout | 18 | 5 | 7 | 67% |
| holiday | 35 | 7 | 16 | 66% |
| adult | 19 | 4 | 8 | 63% |
| restaurant | 19 | 4 | 8 | 63% |
| dinner | 19 | 4 | 8 | 63% |
| friends | 19 | 4 | 8 | 63% |
| party | 19 | 4 | 8 | 63% |
| multi-part | 19 | 4 | 8 | 63% |
| all-day | 19 | 4 | 8 | 63% |
| internal | 35 | 10 | 12 | 63% |
| offer | 16 | 10 | 0 | 62% |
| deadline | 16 | 10 | 0 | 62% |
| tricky | 16 | 10 | 0 | 62% |
| survey | 16 | 10 | 0 | 62% |
| feedback | 16 | 10 | 0 | 62% |
| customer-service | 16 | 10 | 0 | 62% |
| business | 16 | 7 | 3 | 62% |
| virtual | 50 | 16 | 15 | 62% |
| tech | 50 | 14 | 16 | 60% |
| promo | 32 | 19 | 0 | 59% |
| evening | 57 | 11 | 22 | 58% |
| afternoon | 38 | 8 | 14 | 58% |
| legal | 35 | 11 | 9 | 57% |
| kids | 53 | 13 | 17 | 57% |
| marketing | 16 | 9 | 0 | 56% |
| sale | 16 | 9 | 0 | 56% |
| monthly | 16 | 4 | 5 | 56% |
| book-club | 16 | 4 | 5 | 56% |
| workshop | 17 | 4 | 5 | 53% |
| in-person | 17 | 4 | 5 | 53% |
| accountant | 19 | 4 | 6 | 53% |
| tax | 19 | 4 | 6 | 53% |
| cpa | 19 | 4 | 6 | 53% |
| time-range | 19 | 5 | 5 | 53% |
| venue | 19 | 5 | 5 | 53% |
| engagement | 19 | 4 | 6 | 53% |
| winery | 19 | 4 | 6 | 53% |
| outdoor | 19 | 4 | 6 | 53% |
| work | 63 | 14 | 18 | 51% |
| agenda | 34 | 4 | 13 | 50% |
| planning | 18 | 4 | 5 | 50% |
| no_events | 16 | 8 | 0 | 50% |
| promotional | 16 | 8 | 0 | 50% |
| mall | 16 | 8 | 0 | 50% |
| complex | 33 | 8 | 8 | 48% |
| professional | 52 | 11 | 14 | 48% |
| medical | 69 | 12 | 21 | 48% |
| office | 19 | 3 | 6 | 47% |
| field-trip | 17 | 4 | 4 | 47% |
| permission | 17 | 4 | 4 | 47% |
| financial | 51 | 17 | 6 | 45% |
| retail | 16 | 7 | 0 | 44% |
| shipping | 16 | 7 | 0 | 44% |
| delivery | 16 | 7 | 0 | 44% |
| tracking | 16 | 7 | 0 | 44% |
| negative-test | 224 | 97 | 0 | 43% |
| shopping | 32 | 12 | 0 | 38% |
| terms | 16 | 6 | 0 | 38% |
| policy | 16 | 6 | 0 | 38% |
| birthday | 70 | 13 | 13 | 37% |
| wedding | 35 | 4 | 9 | 37% |
| conference | 66 | 16 | 8 | 36% |
| parent-teacher | 17 | 4 | 2 | 35% |
| education | 17 | 4 | 2 | 35% |
| order | 32 | 11 | 0 | 34% |
| receipt | 32 | 11 | 0 | 34% |
| bank | 16 | 5 | 0 | 31% |
| statement | 16 | 5 | 0 | 31% |
| security | 16 | 5 | 0 | 31% |
| password | 16 | 5 | 0 | 31% |
| account | 16 | 5 | 0 | 31% |
| social | 64 | 9 | 6 | 23% |
| notification | 16 | 3 | 0 | 19% |
| linkedin | 16 | 3 | 0 | 19% |
| no-match | 112 | 17 | 0 | 15% |
| dedup | 240 | 36 | 0 | 15% |
| match | 128 | 19 | 0 | 15% |
| different-event | 32 | 4 | 0 | 12% |
| travel | 32 | 3 | 1 | 12% |
| different-date | 16 | 2 | 0 | 12% |
| modality-change | 16 | 0 | 2 | 12% |
| duration-change | 16 | 0 | 1 | 6% |
| time-update | 32 | 0 | 2 | 6% |
| location-update | 32 | 0 | 2 | 6% |
| logistics | 32 | 0 | 2 | 6% |
| dress-code | 16 | 0 | 1 | 6% |
| description-enrichment | 112 | 0 | 4 | 4% |
| merge | 240 | 0 | 8 | 3% |
| reschedule | 32 | 0 | 1 | 3% |

## Cost Analysis

### Per-Eval Cost

| Model | Extract Avg | Compare Avg | Merge Avg | Total |
|-------|-------------|-------------|-----------|-------|
| MiniMax-M2.5 (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| claude-haiku-4-5-20251001 (low) | $0.002589 | $0.000963 | $0.001051 | $0.2192 |
| claude-haiku-4-5-20251001 (none) | $0.004883 | $0.000000 | $0.000000 | $0.0146 |
| claude-sonnet-4-6 (low) | $0.008906 | $0.000000 | $0.000000 | $0.4186 |
| claude-sonnet-4-6 (none) | $0.012225 | $0.003331 | $0.003966 | $1.0019 |
| deepseek-chat (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gemini-3-flash-preview (low) | $0.000477 | $0.000057 | $0.000063 | $0.0732 |
| gemini-3-flash-preview (medium) | $0.000035 | $0.000090 | $0.000000 | $0.0039 |
| gemini-3-flash-preview (none) | $0.000033 | $0.000092 | $0.000000 | $0.0038 |
| glm-4.6v-flash (low) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| glm-4.6v-flash (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gpt-4o-mini (low) | $0.000243 | $0.000000 | $0.000000 | $0.0044 |
| gpt-5-mini (low) | $0.001641 | $0.000360 | $0.000517 | $0.1330 |
| gpt-5-mini (medium) | $0.002739 | $0.000655 | $0.000947 | $0.2240 |
| gpt-5-nano (low) | $0.000644 | $0.000168 | $0.000298 | $0.0760 |
| gpt-5-nano (medium) | $0.001304 | $0.000578 | $0.000709 | $0.1145 |
| gpt-5.2 (low) | $0.008267 | $0.002013 | $0.002376 | $0.6693 |
| gpt-5.2 (medium) | $0.010752 | $0.002168 | $0.002708 | $0.8580 |
| kimi-k2.5 (low) | $0.000000 | $0.002498 | $0.003770 | $0.0940 |
| kimi-k2.5 (none) | $0.007306 | $0.000000 | $0.000000 | $0.0219 |
| qwen-vl-max (none) | $0.003940 | $0.000000 | $0.000000 | $0.0118 |
| qwen3-vl-flash (low) | $0.000977 | $0.000509 | $0.000699 | $0.1779 |
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
| claude-haiku-4-5-20251001 (low) | $0.16 | $0.50 | $1.74 |
| claude-haiku-4-5-20251001 (none) | $0.24 | $0.73 | $2.44 |
| claude-sonnet-4-6 (low) | $0.45 | $1.34 | $4.45 |
| claude-sonnet-4-6 (none) | $0.72 | $2.23 | $7.71 |
| deepseek-chat (none) | $0.00 | $0.00 | $0.00 |
| gemini-3-flash-preview (low) | $0.03 | $0.08 | $0.26 |
| gemini-3-flash-preview (medium) | $0.00 | $0.01 | $0.04 |
| gemini-3-flash-preview (none) | $0.00 | $0.01 | $0.04 |
| glm-4.6v-flash (low) | $0.00 | $0.00 | $0.00 |
| glm-4.6v-flash (none) | $0.00 | $0.00 | $0.00 |
| gpt-4o-mini (low) | $0.01 | $0.04 | $0.12 |
| gpt-5-mini (low) | $0.09 | $0.29 | $1.01 |
| gpt-5-mini (medium) | $0.16 | $0.50 | $1.71 |
| gpt-5-nano (low) | $0.04 | $0.12 | $0.42 |
| gpt-5-nano (medium) | $0.08 | $0.27 | $0.93 |
| gpt-5.2 (low) | $0.48 | $1.48 | $5.09 |
| gpt-5.2 (medium) | $0.61 | $1.88 | $6.43 |
| kimi-k2.5 (low) | $0.09 | $0.33 | $1.31 |
| kimi-k2.5 (none) | $0.37 | $1.10 | $3.65 |
| qwen-vl-max (none) | $0.20 | $0.59 | $1.97 |
| qwen3-vl-flash (low) | $0.07 | $0.21 | $0.75 |
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
| claude-haiku-4-5-20251001 (low) | 1377 | 257 | 168295 |
| claude-haiku-4-5-20251001 (none) | 3141 | 593 | 11200 |
| claude-sonnet-4-6 (low) | 1814 | 231 | 96116 |
| claude-sonnet-4-6 (none) | 1766 | 295 | 212332 |
| deepseek-chat (none) | 0 | 0 | 0 |
| gemini-3-flash-preview (low) | 1554 | 204 | 362158 |
| gemini-3-flash-preview (medium) | 138 | 29 | 17201 |
| gemini-3-flash-preview (none) | 139 | 27 | 17068 |
| glm-4.6v-flash (low) | 756 | 1066 | 185819 |
| glm-4.6v-flash (none) | 3551 | 2120 | 17011 |
| gpt-4o-mini (low) | 1007 | 153 | 20887 |
| gpt-5-mini (low) | 1370 | 474 | 189950 |
| gpt-5-mini (medium) | 1332 | 921 | 232059 |
| gpt-5-nano (low) | 1311 | 1222 | 347066 |
| gpt-5-nano (medium) | 1416 | 2602 | 413818 |
| gpt-5.2 (low) | 1332 | 298 | 167883 |
| gpt-5.2 (medium) | 1332 | 428 | 181361 |
| kimi-k2.5 (low) | 107 | 286 | 40081 |
| kimi-k2.5 (none) | 2907 | 1854 | 14283 |
| qwen-vl-max (none) | 2565 | 590 | 9466 |
| qwen3-vl-flash (low) | 1357 | 1117 | 507200 |
| qwen3-vl-flash (none) | 3240 | 659 | 11698 |
| qwen3-vl-plus (low) | 3235 | 2573 | 17426 |
| qwen3-vl-plus (medium) | 3235 | 4318 | 22661 |
| qwen3-vl-plus (none) | 3240 | 587 | 11482 |
| qwen3.5-plus (low) | 3282 | 1318 | 13802 |
| qwen3.5-plus (medium) | 3282 | 1558 | 14520 |
| qwen3.5-plus (none) | 3285 | 508 | 11378 |

## Regression Analysis

Multiple code versions detected across results.

| code_hash | prompt_hash | Change Type |
|-----------|-------------|-------------|
| `274b820b8ecc` | `N/A (pre-prompt_hash tracking)` | baseline |
| `2bf536dc0a22` | `N/A (pre-prompt_hash tracking)` | baseline |
| `4dece2183c36` | `f127fc68f43d` | prompt changed |
| `6e8b4c59aa00` | `N/A (pre-prompt_hash tracking)` | baseline |
| `unknown` | `N/A (pre-prompt_hash tracking)` | baseline |

> **Note:** All versions share the same `prompt_hash` — this is a scaffolding-only change. Scores should be identical; any differences are LLM non-determinism.

