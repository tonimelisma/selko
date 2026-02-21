# Selko LLM Eval Report
Generated: 2026-02-21T18:10:13.214633+00:00

## Eval Run Overview

| Metric | Value |
|--------|-------|
| **Total Eval Cost** | **$4.3228** |
| Total Evals | 1796 (1316 extract, 240 compare, 240 merge) |
| Models Tested | 29 |
| Total Tokens | 3,356,275 |
| Total API Time | 15611s |
| Code Hash | 274b820b8ecc, 2bf536dc0a22, 6e8b4c59aa00, e48a4d609a11, unknown |

## Model Comparison

| Model | Extract | Compare | Merge | Cost | Avg Latency |
|-------|---------|---------|-------|------|-------------|
| MiniMax-M2.5 (none) | 0/1 (0.0%) | - | - | $0.0000 | 11423ms |
| claude-haiku-4-5-20251001 (low) | 13/74 (17.6%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2204 | 2544ms |
| claude-haiku-4-5-20251001 (none) | 0/3 (0.0%) | - | - | $0.0146 | 4734ms |
| claude-sonnet-4-6 (low) | 17/48 (35.4%) | - | - | $0.4236 | 3604ms |
| claude-sonnet-4-6 (none) | 33/74 (44.6%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $1.0069 | 4595ms |
| deepseek-chat (none) | 0/1 (0.0%) | - | - | $0.0000 | 6276ms |
| gemini-3-flash-preview (low) | 73/148 (49.3%) | 15/30 (50.0%) | 13/30 (2.2 avg) | $0.0742 | 8192ms |
| gemini-3-flash-preview (medium) | 0/74 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0039 | 3422ms |
| gemini-3-flash-preview (none) | 0/74 (0.0%) | 13/15 (86.7%) | 0/15 (0.0 avg) | $0.0038 | 2767ms |
| glm-4.6v-flash (low) | 9/73 (12.3%) | 0/15 (0.0%) | 1/15 (0.3 avg) | $0.0000 | 14074ms |
| glm-4.6v-flash (none) | 0/3 (0.0%) | - | - | $0.0000 | 36190ms |
| gpt-4o-mini (low) | 0/18 (0.0%) | - | - | $0.0044 | 4150ms |
| gpt-5-mini (low) | 60/74 (81.1%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.1350 | 8784ms |
| gpt-5-mini (medium) | 26/74 (35.1%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.2247 | 14260ms |
| gpt-5-nano (low) | 17/108 (15.7%) | 15/15 (100.0%) | 13/15 (4.9 avg) | $0.0760 | 10902ms |
| gpt-5-nano (medium) | 21/74 (28.4%) | 14/15 (93.3%) | 15/15 (5.0 avg) | $0.1150 | 21292ms |
| gpt-5.2 (low) | 23/74 (31.1%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.6718 | 5126ms |
| gpt-5.2 (medium) | 21/74 (28.4%) | 15/15 (100.0%) | 15/15 (5.0 avg) | $0.8605 | 7442ms |
| kimi-k2.5 (low) | 0/73 (0.0%) | 14/15 (93.3%) | 9/15 (4.2 avg) | $0.0940 | 6572ms |
| kimi-k2.5 (none) | 0/3 (0.0%) | - | - | $0.0219 | 41939ms |
| qwen-vl-max (none) | 0/3 (0.0%) | - | - | $0.0118 | 21302ms |
| qwen3-vl-flash (low) | 60/147 (40.8%) | 30/30 (100.0%) | 30/30 (5.0 avg) | $0.1860 | 9305ms |
| qwen3-vl-flash (none) | 0/3 (0.0%) | - | - | $0.0021 | 8075ms |
| qwen3-vl-plus (low) | 0/3 (0.0%) | - | - | $0.0286 | 32654ms |
| qwen3-vl-plus (medium) | 0/3 (0.0%) | - | - | $0.0453 | 53943ms |
| qwen3-vl-plus (none) | 0/3 (0.0%) | - | - | $0.0095 | 10558ms |
| qwen3.5-plus (low) | 0/3 (0.0%) | - | - | $0.0332 | 18636ms |
| qwen3.5-plus (medium) | 0/3 (0.0%) | - | - | $0.0378 | 23866ms |
| qwen3.5-plus (none) | 0/3 (0.0%) | - | - | $0.0176 | 8327ms |
| **TOTAL** | | | | **$4.3228** | |

*Note: Models ran different numbers of extract fixtures (1, 3, 18, 48, 73, 74, 108, 147, 148). Text-only models skip vision fixtures (images, PDFs), so pass rates are not directly comparable.*

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
| gemini-3-flash-preview (low) | 73 | 59 | 16 | 4.0/5 | $0.0708 |
| gemini-3-flash-preview (medium) | 0 | 3 | 71 | 0.1/5 | $0.0026 |
| gemini-3-flash-preview (none) | 0 | 3 | 71 | 0.1/5 | $0.0024 |
| glm-4.6v-flash (low) | 9 | 5 | 59 | 0.9/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 3 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 18 | 0 | 4.0/5 | $0.0044 |
| gpt-5-mini (low) | 60 | 9 | 5 | 4.5/5 | $0.1209 |
| gpt-5-mini (medium) | 26 | 44 | 4 | 3.5/5 | $0.2006 |
| gpt-5-nano (low) | 17 | 83 | 8 | 3.3/5 | $0.0690 |
| gpt-5-nano (medium) | 21 | 45 | 8 | 3.3/5 | $0.0957 |
| gpt-5.2 (low) | 23 | 47 | 4 | 3.3/5 | $0.6059 |
| gpt-5.2 (medium) | 21 | 48 | 5 | 3.3/5 | $0.7874 |
| kimi-k2.5 (low) | 0 | 0 | 73 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 1 | 2.7/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 3 | 0 | 2.3/5 | $0.0118 |
| qwen3-vl-flash (low) | 60 | 69 | 18 | 3.8/5 | $0.1453 |
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
| gemini-3-flash-preview (low) | 9 | 15 | 4 | 3.6/5 | $0.0415 |
| gemini-3-flash-preview (medium) | 0 | 2 | 12 | 0.4/5 | $0.0023 |
| gemini-3-flash-preview (none) | 0 | 2 | 12 | 0.4/5 | $0.0022 |
| glm-4.6v-flash (low) | 1 | 1 | 11 | 0.7/5 | $0.0000 |
| glm-4.6v-flash (none) | 0 | 0 | 2 | 0.0/5 | $0.0000 |
| gpt-4o-mini (low) | 0 | 1 | 0 | 4.0/5 | $0.0006 |
| gpt-5-mini (low) | 7 | 5 | 2 | 3.9/5 | $0.0416 |
| gpt-5-mini (medium) | 2 | 10 | 2 | 2.8/5 | $0.0734 |
| gpt-5-nano (low) | 3 | 11 | 1 | 2.9/5 | $0.0109 |
| gpt-5-nano (medium) | 4 | 9 | 1 | 3.3/5 | $0.0282 |
| gpt-5.2 (low) | 3 | 10 | 1 | 2.9/5 | $0.2396 |
| gpt-5.2 (medium) | 3 | 10 | 1 | 3.1/5 | $0.3075 |
| kimi-k2.5 (low) | 0 | 0 | 13 | 0.0/5 | $0.0000 |
| kimi-k2.5 (none) | 0 | 2 | 0 | 4.0/5 | $0.0219 |
| qwen-vl-max (none) | 0 | 2 | 0 | 2.0/5 | $0.0101 |
| qwen3-vl-flash (low) | 8 | 10 | 9 | 2.8/5 | $0.0326 |
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
| gemini-3-flash-preview (low) | 10 | 12 | 3.9/5 |
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
| qwen3-vl-flash (low) | 9 | 12 | 4.3/5 |

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
| gemini-3-flash-preview (low) | 9 | 11 | 3.9/5 |
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
| qwen3-vl-flash (low) | 9 | 11 | 4.2/5 |
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
| gemini-3-flash-preview (low) | 6 | 6 | 4.3/5 |
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
| qwen3-vl-flash (low) | 3 | 9 | 4.0/5 |

**conferences**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 1 | 6 | 3.4/5 |
| claude-sonnet-4-6 (low) | 2 | 5 | 3.1/5 |
| claude-sonnet-4-6 (none) | 2 | 5 | 3.1/5 |
| gemini-3-flash-preview (low) | 6 | 8 | 3.7/5 |
| gemini-3-flash-preview (medium) | 0 | 7 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 7 | 0.0/5 |
| glm-4.6v-flash (low) | 0 | 7 | 0.6/5 |
| gpt-5-mini (low) | 5 | 2 | 4.3/5 |
| gpt-5-mini (medium) | 1 | 6 | 2.9/5 |
| gpt-5-nano (low) | 1 | 6 | 2.9/5 |
| gpt-5-nano (medium) | 0 | 7 | 2.6/5 |
| gpt-5.2 (low) | 1 | 6 | 2.6/5 |
| gpt-5.2 (medium) | 0 | 7 | 2.3/5 |
| kimi-k2.5 (low) | 0 | 7 | 0.0/5 |
| qwen3-vl-flash (low) | 4 | 10 | 3.6/5 |

**school**

| Model | Pass | Fail | Avg Rating |
|-------|------|------|------------|
| claude-haiku-4-5-20251001 (low) | 3 | 11 | 2.8/5 |
| claude-haiku-4-5-20251001 (none) | 0 | 2 | 3.0/5 |
| claude-sonnet-4-6 (low) | 3 | 3 | 4.0/5 |
| claude-sonnet-4-6 (none) | 5 | 9 | 3.6/5 |
| gemini-3-flash-preview (low) | 9 | 19 | 4.0/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.4/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.4/5 |
| glm-4.6v-flash (low) | 0 | 14 | 0.5/5 |
| glm-4.6v-flash (none) | 0 | 2 | 0.0/5 |
| gpt-5-mini (low) | 10 | 4 | 4.6/5 |
| gpt-5-mini (medium) | 2 | 12 | 3.1/5 |
| gpt-5-nano (low) | 2 | 12 | 2.9/5 |
| gpt-5-nano (medium) | 4 | 10 | 3.4/5 |
| gpt-5.2 (low) | 2 | 12 | 2.9/5 |
| gpt-5.2 (medium) | 2 | 12 | 3.1/5 |
| kimi-k2.5 (low) | 0 | 14 | 0.0/5 |
| kimi-k2.5 (none) | 0 | 2 | 4.0/5 |
| qwen-vl-max (none) | 0 | 2 | 2.0/5 |
| qwen3-vl-flash (low) | 8 | 20 | 3.5/5 |
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
| gemini-3-flash-preview (low) | 21 | 7 | 4.0/5 |
| gemini-3-flash-preview (medium) | 0 | 14 | 0.0/5 |
| gemini-3-flash-preview (none) | 0 | 14 | 0.0/5 |
| glm-4.6v-flash (low) | 9 | 5 | 3.2/5 |
| gpt-5-mini (low) | 9 | 5 | 3.6/5 |
| gpt-5-mini (medium) | 12 | 2 | 4.4/5 |
| gpt-5-nano (low) | 8 | 6 | 3.3/5 |
| gpt-5-nano (medium) | 8 | 6 | 3.3/5 |
| gpt-5.2 (low) | 12 | 2 | 4.4/5 |
| gpt-5.2 (medium) | 11 | 3 | 4.1/5 |
| kimi-k2.5 (low) | 0 | 14 | 0.0/5 |
| qwen3-vl-flash (low) | 16 | 12 | 3.1/5 |

## Compare (Dedup) Results

| Model | Correct | Wrong | Accuracy | Cost |
|-------|---------|-------|----------|------|
| claude-haiku-4-5-20251001 (low) | 15 | 0 | 100.0% | $0.0144 |
| claude-sonnet-4-6 (none) | 15 | 0 | 100.0% | $0.0500 |
| gemini-3-flash-preview (low) | 15 | 15 | 50.0% | $0.0017 |
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
| qwen3-vl-flash (low) | 30 | 0 | 100.0% | $0.0162 |

## Merge Results

| Model | Avg Rating | Pass (5/5) | Cost |
|-------|------------|------------|------|
| claude-haiku-4-5-20251001 (low) | 5.0/5 | 15/15 | $0.0158 |
| claude-sonnet-4-6 (none) | 5.0/5 | 15/15 | $0.0595 |
| gemini-3-flash-preview (low) | 2.2/5 | 13/30 | $0.0017 |
| gemini-3-flash-preview (medium) | 0.0/5 | 0/15 | $0.0000 |
| gemini-3-flash-preview (none) | 0.0/5 | 0/15 | $0.0000 |
| glm-4.6v-flash (low) | 0.3/5 | 1/15 | $0.0000 |
| gpt-5-mini (low) | 5.0/5 | 15/15 | $0.0083 |
| gpt-5-mini (medium) | 5.0/5 | 15/15 | $0.0142 |
| gpt-5-nano (low) | 4.9/5 | 13/15 | $0.0045 |
| gpt-5-nano (medium) | 5.0/5 | 15/15 | $0.0106 |
| gpt-5.2 (low) | 5.0/5 | 15/15 | $0.0356 |
| gpt-5.2 (medium) | 5.0/5 | 15/15 | $0.0406 |
| kimi-k2.5 (low) | 4.2/5 | 9/15 | $0.0565 |
| qwen3-vl-flash (low) | 5.0/5 | 30/30 | $0.0244 |

## Failure Patterns

| Tag | Total | Fail | Partial | Failure Rate |
|-----|-------|------|---------|--------------|
| csv | 17 | 4 | 13 | 100% |
| schedule | 17 | 4 | 13 | 100% |
| multi-attachment | 16 | 8 | 8 | 100% |
| digest | 43 | 32 | 11 | 100% |
| author-visit | 27 | 22 | 5 | 100% |
| multi-event | 32 | 19 | 12 | 97% |
| client | 18 | 7 | 10 | 94% |
| call | 18 | 7 | 10 | 94% |
| txt | 18 | 5 | 12 | 94% |
| extracurricular | 16 | 12 | 3 | 94% |
| community | 32 | 17 | 12 | 91% |
| multiple-events | 52 | 15 | 32 | 90% |
| attachment | 70 | 37 | 26 | 90% |
| retirement | 19 | 4 | 13 | 89% |
| lunch | 19 | 4 | 13 | 89% |
| celebration | 19 | 4 | 13 | 89% |
| transfer | 18 | 4 | 12 | 89% |
| shuttle | 18 | 4 | 12 | 89% |
| airport | 18 | 4 | 12 | 89% |
| pickup | 36 | 10 | 22 | 89% |
| rental | 18 | 6 | 10 | 89% |
| dropoff | 18 | 6 | 10 | 89% |
| calendar | 77 | 38 | 30 | 88% |
| summit | 17 | 11 | 4 | 88% |
| multiple-sessions | 17 | 11 | 4 | 88% |
| itinerary | 17 | 7 | 8 | 88% |
| daycare | 75 | 28 | 38 | 88% |
| forwarded | 16 | 6 | 8 | 88% |
| borderline | 16 | 8 | 6 | 88% |
| calendar-invite | 31 | 9 | 18 | 87% |
| meeting | 52 | 23 | 22 | 87% |
| car | 37 | 11 | 21 | 86% |
| performance | 51 | 24 | 20 | 86% |
| multi-day | 68 | 40 | 18 | 85% |
| 1:1 | 47 | 16 | 24 | 85% |
| manager | 47 | 16 | 24 | 85% |
| registration | 33 | 16 | 12 | 85% |
| pdf | 91 | 45 | 32 | 85% |
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
| vet | 18 | 4 | 11 | 83% |
| pet | 18 | 4 | 11 | 83% |
| animal | 18 | 4 | 11 | 83% |
| all-hands | 18 | 4 | 11 | 83% |
| company | 18 | 4 | 11 | 83% |
| announcement | 18 | 4 | 11 | 83% |
| town-hall | 18 | 4 | 11 | 83% |
| board | 18 | 3 | 12 | 83% |
| executive | 18 | 3 | 12 | 83% |
| ics | 18 | 14 | 1 | 83% |
| annual | 18 | 6 | 9 | 83% |
| standup | 18 | 4 | 11 | 83% |
| daily | 18 | 4 | 11 | 83% |
| time-change | 18 | 4 | 11 | 83% |
| flight | 18 | 4 | 11 | 83% |
| airline | 18 | 4 | 11 | 83% |
| markdown | 17 | 14 | 0 | 82% |
| webinar | 17 | 4 | 10 | 82% |
| online | 17 | 4 | 10 | 82% |
| team | 34 | 8 | 20 | 82% |
| play | 17 | 6 | 8 | 82% |
| arts | 17 | 6 | 8 | 82% |
| multiple-shows | 17 | 6 | 8 | 82% |
| newsletter | 75 | 44 | 17 | 81% |
| biweekly | 16 | 7 | 6 | 81% |
| weekly | 16 | 4 | 9 | 81% |
| real-world | 247 | 129 | 71 | 81% |
| hr | 36 | 10 | 19 | 81% |
| salon | 19 | 4 | 11 | 79% |
| haircut | 19 | 4 | 11 | 79% |
| personal-care | 19 | 4 | 11 | 79% |
| interview | 18 | 4 | 10 | 78% |
| job | 18 | 4 | 10 | 78% |
| hiring | 18 | 4 | 10 | 78% |
| train | 18 | 4 | 10 | 78% |
| amtrak | 18 | 4 | 10 | 78% |
| images | 124 | 71 | 24 | 77% |
| training | 51 | 14 | 25 | 76% |
| corporate | 17 | 6 | 7 | 76% |
| mandatory | 17 | 6 | 7 | 76% |
| booking | 54 | 13 | 28 | 76% |
| city | 16 | 12 | 0 | 75% |
| public-comment | 16 | 12 | 0 | 75% |
| doctor | 19 | 4 | 10 | 74% |
| confirmation | 19 | 4 | 10 | 74% |
| lawyer | 19 | 5 | 9 | 74% |
| consultation | 19 | 5 | 9 | 74% |
| housewarming | 19 | 4 | 10 | 74% |
| open-house | 19 | 4 | 10 | 74% |
| quarterly | 34 | 10 | 15 | 74% |
| review | 34 | 13 | 12 | 74% |
| government | 33 | 17 | 7 | 73% |
| kickoff | 36 | 11 | 15 | 72% |
| project | 36 | 11 | 15 | 72% |
| public-hearing | 17 | 5 | 7 | 71% |
| sports | 17 | 4 | 8 | 71% |
| soccer | 17 | 4 | 8 | 71% |
| game | 17 | 4 | 8 | 71% |
| recurring | 64 | 22 | 23 | 70% |
| school | 283 | 111 | 84 | 69% |
| casual | 38 | 8 | 18 | 68% |
| party | 19 | 4 | 9 | 68% |
| graduation | 36 | 11 | 13 | 67% |
| hotel | 18 | 5 | 7 | 67% |
| checkin | 18 | 5 | 7 | 67% |
| checkout | 18 | 5 | 7 | 67% |
| ceremony | 17 | 7 | 4 | 65% |
| formal | 73 | 17 | 30 | 64% |
| adult | 19 | 4 | 8 | 63% |
| restaurant | 19 | 4 | 8 | 63% |
| dinner | 19 | 4 | 8 | 63% |
| friends | 19 | 4 | 8 | 63% |
| multi-part | 19 | 4 | 8 | 63% |
| all-day | 19 | 4 | 8 | 63% |
| internal | 35 | 10 | 12 | 63% |
| holiday | 35 | 7 | 15 | 63% |
| offer | 16 | 10 | 0 | 62% |
| deadline | 16 | 10 | 0 | 62% |
| tricky | 16 | 10 | 0 | 62% |
| survey | 16 | 10 | 0 | 62% |
| feedback | 16 | 10 | 0 | 62% |
| customer-service | 16 | 10 | 0 | 62% |
| business | 16 | 7 | 3 | 62% |
| tech | 50 | 15 | 16 | 62% |
| virtual | 50 | 15 | 16 | 62% |
| afternoon | 38 | 8 | 15 | 61% |
| evening | 57 | 11 | 22 | 58% |
| legal | 35 | 11 | 9 | 57% |
| kids | 53 | 12 | 18 | 57% |
| no_events | 16 | 9 | 0 | 56% |
| monthly | 16 | 4 | 5 | 56% |
| book-club | 16 | 4 | 5 | 56% |
| promo | 32 | 17 | 0 | 53% |
| workshop | 17 | 4 | 5 | 53% |
| in-person | 17 | 4 | 5 | 53% |
| field-trip | 17 | 4 | 5 | 53% |
| permission | 17 | 4 | 5 | 53% |
| accountant | 19 | 4 | 6 | 53% |
| tax | 19 | 4 | 6 | 53% |
| cpa | 19 | 4 | 6 | 53% |
| engagement | 19 | 4 | 6 | 53% |
| winery | 19 | 4 | 6 | 53% |
| outdoor | 19 | 4 | 6 | 53% |
| financial | 51 | 20 | 6 | 51% |
| work | 63 | 14 | 18 | 51% |
| agenda | 34 | 5 | 12 | 50% |
| planning | 18 | 4 | 5 | 50% |
| retail | 16 | 8 | 0 | 50% |
| shipping | 16 | 8 | 0 | 50% |
| delivery | 16 | 8 | 0 | 50% |
| tracking | 16 | 8 | 0 | 50% |
| professional | 52 | 11 | 14 | 48% |
| medical | 69 | 12 | 21 | 48% |
| time-range | 19 | 4 | 5 | 47% |
| venue | 19 | 4 | 5 | 47% |
| office | 19 | 3 | 6 | 47% |
| conference | 83 | 31 | 8 | 47% |
| complex | 33 | 7 | 8 | 45% |
| bank | 16 | 7 | 0 | 44% |
| statement | 16 | 7 | 0 | 44% |
| negative-test | 224 | 98 | 0 | 44% |
| marketing | 16 | 7 | 0 | 44% |
| sale | 16 | 7 | 0 | 44% |
| order | 32 | 12 | 0 | 38% |
| receipt | 32 | 12 | 0 | 38% |
| promotional | 16 | 6 | 0 | 38% |
| mall | 16 | 6 | 0 | 38% |
| terms | 16 | 6 | 0 | 38% |
| policy | 16 | 6 | 0 | 38% |
| wedding | 35 | 4 | 9 | 37% |
| birthday | 70 | 12 | 13 | 36% |
| parent-teacher | 17 | 4 | 2 | 35% |
| education | 17 | 4 | 2 | 35% |
| shopping | 32 | 10 | 0 | 31% |
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
| claude-haiku-4-5-20251001 (low) | $0.002570 | $0.000963 | $0.001051 | $0.2204 |
| claude-haiku-4-5-20251001 (none) | $0.004883 | $0.000000 | $0.000000 | $0.0146 |
| claude-sonnet-4-6 (low) | $0.008825 | $0.000000 | $0.000000 | $0.4236 |
| claude-sonnet-4-6 (none) | $0.012128 | $0.003331 | $0.003966 | $1.0069 |
| deepseek-chat (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gemini-3-flash-preview (low) | $0.000478 | $0.000057 | $0.000056 | $0.0742 |
| gemini-3-flash-preview (medium) | $0.000035 | $0.000090 | $0.000000 | $0.0039 |
| gemini-3-flash-preview (none) | $0.000033 | $0.000092 | $0.000000 | $0.0038 |
| glm-4.6v-flash (low) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| glm-4.6v-flash (none) | $0.000000 | $0.000000 | $0.000000 | $0.0000 |
| gpt-4o-mini (low) | $0.000243 | $0.000000 | $0.000000 | $0.0044 |
| gpt-5-mini (low) | $0.001634 | $0.000391 | $0.000552 | $0.1350 |
| gpt-5-mini (medium) | $0.002711 | $0.000655 | $0.000947 | $0.2247 |
| gpt-5-nano (low) | $0.000639 | $0.000168 | $0.000298 | $0.0760 |
| gpt-5-nano (medium) | $0.001293 | $0.000578 | $0.000709 | $0.1150 |
| gpt-5.2 (low) | $0.008188 | $0.002013 | $0.002376 | $0.6718 |
| gpt-5.2 (medium) | $0.010641 | $0.002168 | $0.002708 | $0.8605 |
| kimi-k2.5 (low) | $0.000000 | $0.002498 | $0.003770 | $0.0940 |
| kimi-k2.5 (none) | $0.007306 | $0.000000 | $0.000000 | $0.0219 |
| qwen-vl-max (none) | $0.003940 | $0.000000 | $0.000000 | $0.0118 |
| qwen3-vl-flash (low) | $0.000989 | $0.000542 | $0.000814 | $0.1860 |
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
| gemini-3-flash-preview (low) | $0.03 | $0.08 | $0.26 |
| gemini-3-flash-preview (medium) | $0.00 | $0.01 | $0.04 |
| gemini-3-flash-preview (none) | $0.00 | $0.01 | $0.04 |
| glm-4.6v-flash (low) | $0.00 | $0.00 | $0.00 |
| glm-4.6v-flash (none) | $0.00 | $0.00 | $0.00 |
| gpt-4o-mini (low) | $0.01 | $0.04 | $0.12 |
| gpt-5-mini (low) | $0.10 | $0.30 | $1.02 |
| gpt-5-mini (medium) | $0.16 | $0.49 | $1.69 |
| gpt-5-nano (low) | $0.04 | $0.12 | $0.41 |
| gpt-5-nano (medium) | $0.08 | $0.26 | $0.93 |
| gpt-5.2 (low) | $0.47 | $1.47 | $5.05 |
| gpt-5.2 (medium) | $0.60 | $1.86 | $6.38 |
| kimi-k2.5 (low) | $0.09 | $0.33 | $1.31 |
| kimi-k2.5 (none) | $0.37 | $1.10 | $3.65 |
| qwen-vl-max (none) | $0.20 | $0.59 | $1.97 |
| qwen3-vl-flash (low) | $0.07 | $0.22 | $0.78 |
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
| gemini-3-flash-preview (low) | 1556 | 205 | 366357 |
| gemini-3-flash-preview (medium) | 137 | 28 | 17201 |
| gemini-3-flash-preview (none) | 138 | 27 | 17068 |
| glm-4.6v-flash (low) | 754 | 1058 | 186640 |
| glm-4.6v-flash (none) | 3551 | 2120 | 17011 |
| gpt-4o-mini (low) | 1007 | 153 | 20887 |
| gpt-5-mini (low) | 1409 | 473 | 195772 |
| gpt-5-mini (medium) | 1330 | 914 | 233337 |
| gpt-5-nano (low) | 1310 | 1214 | 348216 |
| gpt-5-nano (medium) | 1413 | 2588 | 416056 |
| gpt-5.2 (low) | 1330 | 295 | 168988 |
| gpt-5.2 (medium) | 1330 | 425 | 182473 |
| kimi-k2.5 (low) | 106 | 283 | 40081 |
| kimi-k2.5 (none) | 2907 | 1854 | 14283 |
| qwen-vl-max (none) | 2565 | 590 | 9466 |
| qwen3-vl-flash (low) | 1388 | 1158 | 526960 |
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
| `6e8b4c59aa00` | `N/A (pre-prompt_hash tracking)` | baseline |
| `e48a4d609a11` | `7d3da1691c9f` | prompt changed |
| `unknown` | `N/A (pre-prompt_hash tracking)` | baseline |

> **Note:** All versions share the same `prompt_hash` — this is a scaffolding-only change. Scores should be identical; any differences are LLM non-determinism.

