# Selko LLM Eval Report
Generated: 2026-02-22T07:05:54.452925+00:00

## Eval Run Overview

| Metric | Value |
|--------|-------|
| **Total Eval Cost** | **$4.5323** |
| Total Evals | 1883 (1373 extract, 255 compare, 255 merge) |
| Models Tested | 29 |
| Total Tokens | 3,519,097 |
| Total API Time | 16777s |
| Code Hash | 274b820b8ecc, 2bf536dc0a22, 31dbdc522bf1, 4dece2183c36, 6e8b4c59aa00, 8ba78dafce23, unknown |

## Model Comparison

| Model | Extract | Compare | Merge | Cost | Avg Latency |
|-------|---------|---------|-------|------|-------------|
| MiniMax-M2.5 (none) | 0/1 (0.0%) | - | - | $0.0000 | 11423ms |
| claude-haiku-4-5-20251001 (low) | 13/73 (17.8%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2192 | 2563ms |
| claude-haiku-4-5-20251001 (none) | 65/72 (90.3%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2514 | 2110ms |
| claude-sonnet-4-6 (low) | 17/47 (36.2%) | - | - | $0.4186 | 3656ms |
| claude-sonnet-4-6 (none) | 33/73 (45.2%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $1.0019 | 4630ms |
| deepseek-chat (none) | 0/1 (0.0%) | - | - | $0.0000 | 6276ms |
| gemini-3-flash-preview (low) | 71/148 (48.0%) | 14/30 (46.7%) | 13/30 (2.2 avg) | $0.0742 | 13300ms |
| gemini-3-flash-preview (medium) | 0/73 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0039 | 3454ms |
| gemini-3-flash-preview (none) | 0/73 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0038 | 2793ms |
| glm-4.6v-flash (low) | 9/72 (12.5%) | 0/15 (0.0%) | 1/15 (0.3 avg) | $0.0000 | 14048ms |
| glm-4.6v-flash (none) | 0/3 (0.0%) | - | - | $0.0000 | 36190ms |
| gpt-4o-mini (low) | 0/18 (0.0%) | - | - | $0.0044 | 4150ms |
| gpt-5-mini (low) | 66/75 (88.0%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.1324 | 8745ms |
| gpt-5-mini (medium) | 26/73 (35.6%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2240 | 14359ms |
| gpt-5-nano (low) | 17/107 (15.9%) | 15/15 (100.0%) | 13/15 (4.9 avg) | $0.0760 | 10970ms |
| gpt-5-nano (medium) | 21/73 (28.8%) | 14/15 (93.3%) | 15/15 (5.0 avg) | $0.1145 | 21406ms |
| gpt-5.2 (low) | 23/73 (31.5%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.6693 | 5162ms |
| gpt-5.2 (medium) | 21/73 (28.8%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.8580 | 7499ms |
| kimi-k2.5 (low) | 0/72 (0.0%) | 14/15 (93.3%) | 9/15 (4.2 avg) | $0.0940 | 6634ms |
| kimi-k2.5 (none) | 0/3 (0.0%) | - | - | $0.0219 | 41939ms |
| qwen-vl-max (none) | 0/3 (0.0%) | - | - | $0.0118 | 21302ms |
| qwen3-vl-flash (low) | 61/146 (41.8%) | 30/30 (100.0%) | 30/30 (5.0 avg) | $0.1790 | 9036ms |
| qwen3-vl-flash (none) | 0/3 (0.0%) | - | - | $0.0021 | 8075ms |
| qwen3-vl-plus (low) | 0/3 (0.0%) | - | - | $0.0286 | 32654ms |
| qwen3-vl-plus (medium) | 0/3 (0.0%) | - | - | $0.0453 | 53943ms |
| qwen3-vl-plus (none) | 0/3 (0.0%) | - | - | $0.0095 | 10558ms |
| qwen3.5-plus (low) | 0/3 (0.0%) | - | - | $0.0332 | 18636ms |
| qwen3.5-plus (medium) | 0/3 (0.0%) | - | - | $0.0378 | 23866ms |
| qwen3.5-plus (none) | 0/3 (0.0%) | - | - | $0.0176 | 8327ms |
| **TOTAL** | | | | **$4.5323** | |

*Note: Models ran different numbers of extract fixtures (1, 3, 18, 47, 72, 73, 75, 107, 146, 148). Text-only models skip vision fixtures (images, PDFs), so pass rates are not directly comparable.*

## Extraction Results

### All Fixtures

| Model | Pass | Partial | Fail | Avg Rating | Cost |
|-------|------|---------|------|------------|------|
| MiniMax-M2.5 (none) | 0 | 0 | 1 | 0.0/5 | $0.0000 |
| claude-haiku-4-5-20251001 (low) | 13 | 48 | 12 | 3.3/5 | $0.1890 |
| claude-haiku-4-5-20251001 (none) | 65 | 5 | 2 | 4.8/5 | $0.2215 |
| claude-sonnet-4-6 (low) | 17 | 29 | 1 | 3.7/5 | $0.4186 |
| claude-sonnet-4-6 (none) | 33 | 38 | 2 | 3.8/5 | $0.8925 |
| deepseek-chat (none) | 0 | 0 | 1 | 0.0/5 | $0.0000 |
| gemini-3-flash-preview (low) | 71 | 57 | 20 | 3.9/5 | $0.0708 |
| gemini-3-flash-preview (medium) | 0 | 3 | 70 | 0.1/5 | $0.0026 |
| gemini-3-flash-preview (none) | 0 | 3 | 70 | 0.1/5 | $0.0024 |
| glm-4.6v-flash (low) | 9 | 5 | 58 | 0.9/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 3 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 18 | 0 | 4.0/5 | $0.0044 |
| gpt-5-mini (low) | 66 | 4 | 5 | 4.7/5 | $0.1189 |
| gpt-5-mini (medium) | 26 | 44 | 3 | 3.5/5 | $0.1999 |
| gpt-5-nano (low) | 17 | 83 | 7 | 3.4/5 | $0.0689 |
| gpt-5-nano (medium) | 21 | 45 | 7 | 3.3/5 | $0.0952 |
| gpt-5.2 (low) | 23 | 47 | 3 | 3.3/5 | $0.6035 |
| gpt-5.2 (medium) | 21 | 48 | 4 | 3.3/5 | $0.7849 |
| kimi-k2.5 (low) | 0 | 0 | 72 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 1 | 2.7/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 3 | 0 | 2.3/5 | $0.0118 |
| qwen3-vl-flash (low) | 61 | 65 | 20 | 3.8/5 | $0.1427 |
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
| claude-haiku-4-5-20251001 (none) | 10 | 3 | 0 | 4.7/5 | $0.0791 |
| claude-sonnet-4-6 (low) | 0 | 2 | 0 | 3.0/5 | $0.0290 |
| claude-sonnet-4-6 (none) | 5 | 8 | 1 | 3.6/5 | $0.3311 |
| gemini-3-flash-preview (low) | 11 | 13 | 5 | 3.7/5 | $0.0427 |
| gemini-3-flash-preview (medium) | 0 | 2 | 12 | 0.4/5 | $0.0023 |
| gemini-3-flash-preview (none) | 0 | 2 | 12 | 0.4/5 | $0.0022 |
| glm-4.6v-flash (low) | 1 | 1 | 11 | 0.7/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 2 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 1 | 0 | 4.0/5 | $0.0006 |
| gpt-5-mini (low) | 11 | 2 | 2 | 4.3/5 | $0.0420 |
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
| claude-haiku-4-5-20251001 (none) | 10 | 1 | 4.9/5 |
| claude-sonnet-4-6 (low) | 7 | 4 | 4.3/5 |
| claude-sonnet-4-6 (none) | 7 | 4 | 4.4/5 |
| gemini-3-flash-preview (low) | 10 | 12 | 3.9/5 |
| gemini-3-flash-preview (medium) | 0 | 11 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 11 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 10 | 0.4/5 |
| gpt-4o-mini (low) | 0 | 11 | 4.0/5 |
| gpt-5-mini (low) | 11 | 0 | 5.0/5 |
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
| claude-haiku-4-5-20251001 (none) | 8 | 0 | 5.0/5 |
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
| claude-haiku-4-5-20251001 (none) | 9 | 1 | 4.8/5 |
| claude-sonnet-4-6 (low) | 1 | 9 | 3.0/5 |
| claude-sonnet-4-6 (none) | 1 | 9 | 3.0/5 |
| deepseek-chat (none) | 0 | 1 | 0.0/5 |
| gemini-3-flash-preview (low) | 8 | 12 | 3.6/5 |
| gemini-3-flash-preview (medium) | 0 | 10 | 0.3/5 |
| gemini-3-flash-preview (none) | 0 | 10 | 0.3/5 |
| glm-4.6v-flash (low) | 0 | 10 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 1 | 0.0/5 |
| gpt-5-mini (low) | 8 | 2 | 4.6/5 |
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
| claude-haiku-4-5-20251001 (none) | 6 | 0 | 5.0/5 |
| claude-sonnet-4-6 (low) | 2 | 4 | 3.7/5 |
| claude-sonnet-4-6 (none) | 1 | 5 | 3.3/5 |
| gemini-3-flash-preview (low) | 5 | 7 | 4.2/5 |
| gemini-3-flash-preview (medium) | 0 | 6 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 6 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 6 | 0.0/5 |
| gpt-5-mini (low) | 6 | 0 | 5.0/5 |
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
| claude-haiku-4-5-20251001 (none) | 5 | 1 | 4.7/5 |
| claude-sonnet-4-6 (low) | 2 | 4 | 3.5/5 |
| claude-sonnet-4-6 (none) | 2 | 4 | 3.5/5 |
| gemini-3-flash-preview (low) | 6 | 7 | 3.8/5 |
| gemini-3-flash-preview (medium) | 0 | 6 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 6 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 6 | 0.5/5 |
| gpt-5-mini (low) | 6 | 1 | 4.4/5 |
| gpt-5-mini (medium) | 1 | 5 | 3.2/5 |
| gpt-5-nano (low) | 1 | 5 | 3.2/5 |
| gpt-5-nano (medium) | 0 | 6 | 2.8/5 |
| gpt-5.2 (low) | 1 | 5 | 2.8/5 |
| gpt-5.2 (medium) | 0 | 6 | 2.5/5 |
| kimi-k2.5 (low) | 0 | 6 | 0.0/5 |
| qwen3-vl-flash (low) | 5 | 8 | 3.8/5 |

**school**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 3 | 11 | 2.8/5 |
| claude-haiku-4-5-20251001 (none) | 13 | 2 | 4.8/5 |
| claude-sonnet-4-6 (low) | 3 | 3 | 4.0/5 |
| claude-sonnet-4-6 (none) | 5 | 9 | 3.6/5 |
| gemini-3-flash-preview (low) | 12 | 17 | 4.2/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.4/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.4/5 |
| glm-4.6v-flash (low) | 0 | 14 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 2 | 0.0/5 |
| gpt-5-mini (low) | 13 | 2 | 4.9/5 |
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
| claude-haiku-4-5-20251001 (none) | 4 | 0 | 5.0/5 |
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
| claude-haiku-4-5-20251001 (none) | 10 | 2 | 4.3/5 |
| claude-sonnet-4-6 (none) | 13 | 1 | 4.7/5 |
| gemini-3-flash-preview (low) | 18 | 10 | 3.6/5 |
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
| claude-haiku-4-5-20251001 (none) | 15 | 0 | 100.0% | $0.0140 |
| claude-sonnet-4-6 (none) | 15 | 0 | 100.0% | $0.0500 |
| gemini-3-flash-preview (low) | 14 | 16 | 46.7% | $0.0016 |
| gemini-3-flash-preview (medium) | 13 | 2 | 86.7% | $0.0013 |
| gemini-3-flash-preview (none) | 13 | 2 | 86.7% | $0.0014 |
| glm-4.6v-flash (low) | 0 | 15 | 0.0% | $0.0000 |
| gpt-5-mini (low) | 15 | 0 | 100.0% | $0.0059 |
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
| claude-haiku-4-5-20251001 (none) | 5.0/5 | 15/15 | $0.0158 |
| claude-sonnet-4-6 (none) | 5.0/5 | 15/15 | $0.0595 |
| gemini-3-flash-preview (low) | 2.2/5 | 13/30 | $0.0018 |
| gemini-3-flash-preview (medium) | 0.0/5 | 0/15 | $0.0000 |
| gemini-3-flash-preview (none) | 0.0/5 | 0/15 | $0.0000 |
| glm-4.6v-flash (low) | 0.3/5 | 1/15 | $0.0000 |
| gpt-5-mini (low) | 5.0/5 | 15/15 | $0.0076 |
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
| multi-attachment | 17 | 8 | 9 | 100% |
| markdown | 3 | 3 | 0 | 100% |
| txt | 19 | 5 | 13 | 95% |
| summit | 18 | 12 | 4 | 89% |
| multiple-sessions | 18 | 12 | 4 | 89% |
| author-visit | 27 | 20 | 4 | 89% |
| itinerary | 18 | 7 | 9 | 89% |
| daycare | 78 | 28 | 41 | 88% |
| community | 34 | 16 | 14 | 88% |
| forwarded | 17 | 6 | 9 | 88% |
| borderline | 17 | 8 | 7 | 88% |
| calendar | 80 | 38 | 32 | 88% |
| calendar-invite | 31 | 10 | 17 | 87% |
| digest | 44 | 30 | 8 | 86% |
| multi-event | 34 | 18 | 11 | 85% |
| attachment | 59 | 26 | 24 | 85% |
| board | 19 | 3 | 13 | 84% |
| executive | 19 | 3 | 13 | 84% |
| client | 19 | 7 | 9 | 84% |
| call | 19 | 7 | 9 | 84% |
| annual | 19 | 6 | 10 | 84% |
| rental | 19 | 7 | 9 | 84% |
| dropoff | 19 | 7 | 9 | 84% |
| meeting | 55 | 23 | 23 | 84% |
| 1:1 | 48 | 17 | 23 | 83% |
| manager | 48 | 17 | 23 | 83% |
| multi-day | 57 | 28 | 19 | 82% |
| extracurricular | 17 | 11 | 3 | 82% |
| pdf | 95 | 44 | 34 | 82% |
| car | 39 | 12 | 20 | 82% |
| multiple-events | 55 | 15 | 30 | 82% |
| pickup | 38 | 11 | 20 | 82% |
| performance | 54 | 23 | 21 | 81% |
| service | 40 | 9 | 23 | 80% |
| auto | 20 | 5 | 11 | 80% |
| morning | 20 | 5 | 11 | 80% |
| dental | 20 | 4 | 12 | 80% |
| cleaning | 20 | 4 | 12 | 80% |
| reminder | 20 | 4 | 12 | 80% |
| home | 20 | 4 | 12 | 80% |
| repair | 20 | 4 | 12 | 80% |
| time-window | 20 | 4 | 12 | 80% |
| baby-shower | 20 | 4 | 12 | 80% |
| brunch | 20 | 4 | 12 | 80% |
| weekend | 20 | 4 | 12 | 80% |
| retirement | 20 | 4 | 12 | 80% |
| lunch | 20 | 4 | 12 | 80% |
| celebration | 20 | 4 | 12 | 80% |
| vet | 19 | 4 | 11 | 79% |
| pet | 19 | 4 | 11 | 79% |
| animal | 19 | 4 | 11 | 79% |
| all-hands | 19 | 4 | 11 | 79% |
| company | 19 | 4 | 11 | 79% |
| announcement | 19 | 4 | 11 | 79% |
| town-hall | 19 | 4 | 11 | 79% |
| ics | 19 | 14 | 1 | 79% |
| hr | 38 | 10 | 20 | 79% |
| standup | 19 | 4 | 11 | 79% |
| daily | 19 | 4 | 11 | 79% |
| time-change | 19 | 4 | 11 | 79% |
| transfer | 19 | 4 | 11 | 79% |
| shuttle | 19 | 4 | 11 | 79% |
| airport | 19 | 4 | 11 | 79% |
| flight | 19 | 4 | 11 | 79% |
| airline | 19 | 4 | 11 | 79% |
| csv | 18 | 4 | 10 | 78% |
| schedule | 18 | 4 | 10 | 78% |
| webinar | 18 | 4 | 10 | 78% |
| online | 18 | 4 | 10 | 78% |
| team | 36 | 8 | 20 | 78% |
| play | 18 | 6 | 8 | 78% |
| arts | 18 | 6 | 8 | 78% |
| multiple-shows | 18 | 6 | 8 | 78% |
| registration | 35 | 14 | 13 | 77% |
| real-world | 260 | 126 | 73 | 77% |
| biweekly | 17 | 7 | 6 | 76% |
| weekly | 17 | 4 | 9 | 76% |
| salon | 20 | 4 | 11 | 75% |
| haircut | 20 | 4 | 11 | 75% |
| personal-care | 20 | 4 | 11 | 75% |
| interview | 19 | 4 | 10 | 74% |
| job | 19 | 4 | 10 | 74% |
| hiring | 19 | 4 | 10 | 74% |
| train | 19 | 4 | 10 | 74% |
| amtrak | 19 | 4 | 10 | 74% |
| corporate | 18 | 6 | 7 | 72% |
| mandatory | 18 | 6 | 7 | 72% |
| quarterly | 36 | 10 | 16 | 72% |
| review | 36 | 13 | 13 | 72% |
| booking | 57 | 13 | 28 | 72% |
| newsletter | 78 | 41 | 15 | 72% |
| images | 131 | 70 | 22 | 70% |
| doctor | 20 | 4 | 10 | 70% |
| confirmation | 20 | 4 | 10 | 70% |
| lawyer | 20 | 5 | 9 | 70% |
| consultation | 20 | 5 | 9 | 70% |
| housewarming | 20 | 4 | 10 | 70% |
| open-house | 20 | 4 | 10 | 70% |
| training | 54 | 14 | 22 | 67% |
| ceremony | 18 | 8 | 4 | 67% |
| public-hearing | 18 | 5 | 7 | 67% |
| sports | 18 | 4 | 8 | 67% |
| soccer | 18 | 4 | 8 | 67% |
| game | 18 | 4 | 8 | 67% |
| recurring | 68 | 22 | 23 | 66% |
| kickoff | 38 | 11 | 14 | 66% |
| project | 38 | 11 | 14 | 66% |
| casual | 40 | 8 | 18 | 65% |
| school | 297 | 109 | 84 | 65% |
| government | 37 | 17 | 7 | 65% |
| marketing | 17 | 11 | 0 | 65% |
| sale | 17 | 11 | 0 | 65% |
| promo | 34 | 22 | 0 | 65% |
| offer | 17 | 11 | 0 | 65% |
| deadline | 17 | 11 | 0 | 65% |
| tricky | 17 | 11 | 0 | 65% |
| formal | 77 | 18 | 31 | 64% |
| graduation | 38 | 12 | 12 | 63% |
| city | 19 | 12 | 0 | 63% |
| public-comment | 19 | 12 | 0 | 63% |
| hotel | 19 | 5 | 7 | 63% |
| checkin | 19 | 5 | 7 | 63% |
| checkout | 19 | 5 | 7 | 63% |
| holiday | 37 | 7 | 16 | 62% |
| virtual | 53 | 16 | 16 | 60% |
| adult | 20 | 4 | 8 | 60% |
| restaurant | 20 | 4 | 8 | 60% |
| dinner | 20 | 4 | 8 | 60% |
| friends | 20 | 4 | 8 | 60% |
| party | 20 | 4 | 8 | 60% |
| multi-part | 20 | 4 | 8 | 60% |
| all-day | 20 | 4 | 8 | 60% |
| internal | 37 | 10 | 12 | 59% |
| survey | 17 | 10 | 0 | 59% |
| feedback | 17 | 10 | 0 | 59% |
| customer-service | 17 | 10 | 0 | 59% |
| business | 17 | 7 | 3 | 59% |
| evening | 60 | 11 | 22 | 55% |
| afternoon | 40 | 8 | 14 | 55% |
| tech | 53 | 13 | 16 | 55% |
| legal | 37 | 11 | 9 | 54% |
| kids | 56 | 13 | 17 | 54% |
| no_events | 17 | 9 | 0 | 53% |
| monthly | 17 | 4 | 5 | 53% |
| book-club | 17 | 4 | 5 | 53% |
| accountant | 20 | 4 | 6 | 50% |
| tax | 20 | 4 | 6 | 50% |
| cpa | 20 | 4 | 6 | 50% |
| workshop | 18 | 4 | 5 | 50% |
| in-person | 18 | 4 | 5 | 50% |
| time-range | 20 | 5 | 5 | 50% |
| venue | 20 | 5 | 5 | 50% |
| engagement | 20 | 4 | 6 | 50% |
| winery | 20 | 4 | 6 | 50% |
| outdoor | 20 | 4 | 6 | 50% |
| agenda | 36 | 5 | 13 | 50% |
| promotional | 16 | 8 | 0 | 50% |
| mall | 16 | 8 | 0 | 50% |
| work | 65 | 15 | 17 | 49% |
| planning | 19 | 4 | 5 | 47% |
| complex | 35 | 7 | 9 | 46% |
| professional | 55 | 11 | 14 | 45% |
| medical | 73 | 12 | 21 | 45% |
| office | 20 | 3 | 6 | 45% |
| financial | 54 | 18 | 6 | 44% |
| field-trip | 18 | 4 | 4 | 44% |
| permission | 18 | 4 | 4 | 44% |
| negative-test | 236 | 101 | 0 | 43% |
| retail | 17 | 7 | 0 | 41% |
| shipping | 17 | 7 | 0 | 41% |
| delivery | 17 | 7 | 0 | 41% |
| tracking | 17 | 7 | 0 | 41% |
| birthday | 74 | 14 | 13 | 36% |
| shopping | 33 | 12 | 0 | 36% |
| conference | 73 | 18 | 8 | 36% |
| terms | 17 | 6 | 0 | 35% |
| policy | 17 | 6 | 0 | 35% |
| wedding | 37 | 4 | 9 | 35% |
| parent-teacher | 18 | 4 | 2 | 33% |
| education | 18 | 4 | 2 | 33% |
| order | 34 | 11 | 0 | 32% |
| receipt | 34 | 11 | 0 | 32% |
| bank | 17 | 5 | 0 | 29% |
| statement | 17 | 5 | 0 | 29% |
| security | 17 | 5 | 0 | 29% |
| password | 17 | 5 | 0 | 29% |
| account | 17 | 5 | 0 | 29% |
| social | 68 | 9 | 6 | 22% |
| notification | 17 | 3 | 0 | 18% |
| linkedin | 17 | 3 | 0 | 18% |
| match | 136 | 20 | 0 | 15% |
| dedup | 255 | 37 | 0 | 15% |
| no-match | 119 | 17 | 0 | 14% |
| different-event | 34 | 4 | 0 | 12% |
| travel | 34 | 3 | 1 | 12% |
| different-date | 17 | 2 | 0 | 12% |
| modality-change | 17 | 0 | 2 | 12% |
| duration-change | 17 | 0 | 1 | 6% |
| time-update | 34 | 0 | 2 | 6% |
| location-update | 34 | 0 | 2 | 6% |
| logistics | 34 | 0 | 2 | 6% |
| dress-code | 17 | 0 | 1 | 6% |
| description-enrichment | 119 | 0 | 4 | 3% |
| merge | 255 | 0 | 8 | 3% |
| reschedule | 34 | 0 | 1 | 3% |

## Cost Analysis

### Per-Eval Cost

| Model | Extract Avg | Compare Avg | Merge Avg | Total |
|-------|-------------|-------------|-----------|-------|
| MiniMax-M2.5 (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| claude-haiku-4-5-20251001 (low) | $0.002589 | $0.000963 | $0.001051 | $0.2192 |
| claude-haiku-4-5-20251001 (none) | $0.003077 | $0.000936 | $0.001051 | $0.2514 |
| claude-sonnet-4-6 (low) | $0.008906 | $0.000000 | $0.000000 | $0.4186 |
| claude-sonnet-4-6 (none) | $0.012225 | $0.003331 | $0.003966 | $1.0019 |
| deepseek-chat (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gemini-3-flash-preview (low) | $0.000478 | $0.000052 | $0.000060 | $0.0742 |
| gemini-3-flash-preview (medium) | $0.000035 | $0.000090 | $0.000000 | $0.0039 |
| gemini-3-flash-preview (none) | $0.000033 | $0.000092 | $0.000000 | $0.0038 |
| glm-4.6v-flash (low) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| glm-4.6v-flash (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gpt-4o-mini (low) | $0.000243 | $0.000000 | $0.000000 | $0.0044 |
| gpt-5-mini (low) | $0.001585 | $0.000391 | $0.000509 | $0.1324 |
| gpt-5-mini (medium) | $0.002739 | $0.000655 | $0.000947 | $0.2240 |
| gpt-5-nano (low) | $0.000644 | $0.000168 | $0.000298 | $0.0760 |
| gpt-5-nano (medium) | $0.001304 | $0.000578 | $0.000709 | $0.1145 |
| gpt-5.2 (low) | $0.008267 | $0.002013 | $0.002376 | $0.6693 |
| gpt-5.2 (medium) | $0.010752 | $0.002168 | $0.002708 | $0.8580 |
| kimi-k2.5 (low) | $0.000000 | $0.002498 | $0.003770 | $0.0940 |
| kimi-k2.5 (none) | $0.007306 | $0.000000 | $0.000000 | $0.0219 |
| qwen-vl-max (none) | $0.003940 | $0.000000 | $0.000000 | $0.0118 |
| qwen3-vl-flash (low) | $0.000978 | $0.000509 | $0.000699 | $0.1790 |
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
| claude-haiku-4-5-20251001 (none) | $0.18 | $0.57 | $1.98 |
| claude-sonnet-4-6 (low) | $0.45 | $1.34 | $4.45 |
| claude-sonnet-4-6 (none) | $0.72 | $2.23 | $7.71 |
| deepseek-chat (none) | $0.00 | $0.00 | $0.00 |
| gemini-3-flash-preview (low) | $0.03 | $0.08 | $0.26 |
| gemini-3-flash-preview (medium) | $0.00 | $0.01 | $0.04 |
| gemini-3-flash-preview (none) | $0.00 | $0.01 | $0.04 |
| glm-4.6v-flash (low) | $0.00 | $0.00 | $0.00 |
| glm-4.6v-flash (none) | $0.00 | $0.00 | $0.00 |
| gpt-4o-mini (low) | $0.01 | $0.04 | $0.12 |
| gpt-5-mini (low) | $0.09 | $0.29 | $0.99 |
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
| claude-haiku-4-5-20251001 (none) | 1744 | 267 | 205121 |
| claude-sonnet-4-6 (low) | 1814 | 231 | 96116 |
| claude-sonnet-4-6 (none) | 1766 | 295 | 212332 |
| deepseek-chat (none) | 0 | 0 | 0 |
| gemini-3-flash-preview (low) | 1575 | 200 | 369329 |
| gemini-3-flash-preview (medium) | 138 | 29 | 17201 |
| gemini-3-flash-preview (none) | 139 | 27 | 17068 |
| glm-4.6v-flash (low) | 756 | 1066 | 185819 |
| glm-4.6v-flash (none) | 3551 | 2120 | 17011 |
| gpt-4o-mini (low) | 1007 | 153 | 20887 |
| gpt-5-mini (low) | 1356 | 461 | 190729 |
| gpt-5-mini (medium) | 1332 | 921 | 232059 |
| gpt-5-nano (low) | 1311 | 1222 | 347066 |
| gpt-5-nano (medium) | 1416 | 2602 | 413818 |
| gpt-5.2 (low) | 1332 | 298 | 167883 |
| gpt-5.2 (medium) | 1332 | 428 | 181361 |
| kimi-k2.5 (low) | 107 | 286 | 40081 |
| kimi-k2.5 (none) | 2907 | 1854 | 14283 |
| qwen-vl-max (none) | 2565 | 590 | 9466 |
| qwen3-vl-flash (low) | 1359 | 1118 | 510205 |
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
| `31dbdc522bf1` | `b1b75e6301a2` | prompt changed |
| `4dece2183c36` | `f127fc68f43d` | prompt changed |
| `6e8b4c59aa00` | `N/A (pre-prompt_hash tracking)` | baseline |
| `8ba78dafce23` | `N/A (pre-prompt_hash tracking)` | baseline |
| `unknown` | `N/A (pre-prompt_hash tracking)` | baseline |

> **Note:** `prompt_hash` differs between versions — prompt was changed. Run `--compare-baseline` to see score differences.

