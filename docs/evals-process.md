# Evals Process

How to use the eval framework effectively: when to run what, how to interpret results, and what to do next.

For CLI reference and fixture format details, see `backend/tests/eval/README.md`.

---

## Purpose & Philosophy

Evals serve five purposes:

1. **Model selection** — which model gives the best quality/cost/latency tradeoff?
2. **Prompt iteration** — did this prompt change improve extraction quality?
3. **Regression detection** — did a code change break something that was working?
4. **Error analysis** — what patterns of failure exist and what causes them?
5. **Fixture quality** — are our test cases representative and our expected outputs correct?

The core principle: **measure before changing, measure after changing, compare.** Never merge a change to `event_processing.py` without running evals before and after.

Evals are only as good as your fixtures — garbage in, garbage out. If the expected output is wrong, a "failure" is actually the LLM being correct. Review fixtures as carefully as you review code.

---

## The Eval Improvement Loop

```
Measure → Analyze failures → Categorize root cause → Fix → Re-measure → Compare
    ↑                                                                        |
    └──── Add new fixtures from production failures ←────────────────────────┘
```

When something fails, categorize the root cause:

| Root Cause | What to Fix | Example |
|------------|-------------|---------|
| **Prompt issue** | Edit prompt in `event_processing.py` | LLM extracts promotional content as events |
| **Model limitation** | Try a different model or thinking level | Model can't parse dates in images |
| **Fixture issue** | Fix the expected output, or rewrite ambiguous input | Expected title doesn't match reasonable interpretation |
| **Scoring issue** | Adjust thresholds in `eval_config.py` or fix scorer bugs | Title similarity too strict for paraphrased titles |
| **Code issue** | Fix plumbing around the LLM call | JSON parsing error, missing field mapping |

---

## Common Workflows

### Workflow A: Prompt Iteration (most common)

When editing prompts or schemas in `event_processing.py`:

```bash
# 1. Run baseline against default model
uv run python -m backend.tests.eval.run_eval --all --all-operations

# 2. Save the report
uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/reports/baseline.md

# 3. Analyze failures — look at PARTIAL and FAIL results
uv run python -m backend.tests.eval.run_eval --report

# 4. Inspect specific failures
uv run python -m backend.tests.eval.run_eval --show invitations/birthday_party_01

# 5. Edit the prompt in event_processing.py
#    (code_hash changes automatically, so cache invalidates)

# 6. Re-run the same eval
uv run python -m backend.tests.eval.run_eval --all --all-operations

# 7. Save the new report and compare
uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/reports/after-change.md
```

**Decision:** If overall pass rate improved (or held steady) without regressions on previously-passing fixtures → commit. If it regressed → revert.

### Workflow B: Model Benchmarking (periodic)

Compare all configured models head-to-head:

```bash
# Run all fixtures across all models (expensive — uses all provider API keys)
uv run python -m backend.tests.eval.run_eval --all --all-operations --all-models

# Generate the full benchmark report
uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/reports/model-benchmark.md
```

The report shows pass rates, cost, and latency per model. Decision criteria, in order:
1. **Quality** — pass rate is king
2. **Cost** — among models with similar quality, prefer cheaper
3. **Latency** — among models with similar quality and cost, prefer faster

Update the default model in `eval_config.py` (and production config) if switching.

### Workflow C: Regression Check (after code changes)

Quick check that nothing broke — run against the default model only:

```bash
# Fast run — default model, all operations
uv run python -m backend.tests.eval.run_eval --all --all-operations

# Compare pass/fail/partial counts to the last saved report
uv run python -m backend.tests.eval.run_eval --report
```

If scores dropped, investigate which fixtures regressed using `--show <fixture>`.

**Rule:** Never merge a change to `event_processing.py` that makes overall scores worse without a clear justification (e.g., trading one failure for fixing three others).

### Workflow D: Error Analysis (deep dive)

When you need to understand failure patterns systematically:

```bash
# 1. Run eval and view the report
uv run python -m backend.tests.eval.run_eval --all --all-operations --report

# 2. For each PARTIAL and FAIL fixture, inspect expected vs actual
uv run python -m backend.tests.eval.run_eval --show meetings/team_standup_01
uv run python -m backend.tests.eval.run_eval --show travel/flight_confirmation_01
# ... repeat for each failure
```

3. Categorize each failure using the root cause table above
4. Group by category — e.g., "5 failures are all LLM hallucinating events from promotional emails" = one prompt fix
5. Prioritize by count: fix the most common failure pattern first
6. After fixing, re-run to verify the fix and check for regressions

### Workflow E: Adding Fixtures

When a real email is mishandled in production, or you identify an untested edge case:

1. Create a new fixture JSON in the appropriate category directory under `backend/tests/eval/fixtures/`
2. Anonymize PII — replace real names, emails, and addresses
3. Hand-write the expected output (do NOT use LLM output as ground truth)
4. Run the single fixture to confirm it behaves as expected:
   ```bash
   uv run python -m backend.tests.eval.run_eval --fixture category/fixture_name
   ```
5. If it fails and should pass → fix the prompt/code, then re-run full eval to check for regressions
6. If it passes → great, you've added coverage for a case that already works

---

## Fixture Quality Guidelines

- Fixtures should represent **real-world emails**, not contrived edge cases
- Each fixture should test **one thing clearly** — not 5 edge cases stacked together
- Expected outputs must be **reviewed by a human** — the LLM's answer is NOT ground truth
- Difficulty levels should be honest: "easy" means any decent model gets it right, "hard" means even top models struggle
- Review coverage periodically: are there email types users encounter that aren't covered?
- All attachment references must use local files in `fixtures/attachments/` — never external URLs

---

## Interpreting Results

### Rating Scale

| Rating | Label | Meaning |
|--------|-------|---------|
| 5 | Perfect | All fields match within thresholds |
| 4 | Excellent | Minor differences (slight description variation) |
| 3 | Good | Correct event detection, some field issues |
| 2 | Partial | Missed events or significant extraction errors |
| 1 | Failed | Wrong extraction, false positive, or false negative |

### Scoring Thresholds (from `eval_config.py`)

- **Title similarity**: ≥ 0.8 (extraction), ≥ 0.9 (merge)
- **Time tolerance**: ± 30 minutes (extraction), exact (merge)
- **Location similarity**: ≥ 0.7 (extraction), ≥ 0.8 (merge)
- **Confidence minimum**: ≥ 0.5

### What the Numbers Tell You

- **High PARTIAL count** often means scoring thresholds need review, not prompt issues. Check if the LLM output is reasonable but the scorer is too strict.
- **Compare scores across models** to distinguish "prompt problem" (all models fail) from "model limitation" (one model fails, others pass).
- **Category-level patterns** reveal prompt gaps. If all `travel/` fixtures fail, the prompt probably doesn't handle booking confirmations well.
- **Sudden score drops** after a code change = regression. Revert or fix immediately.

---

## Caching Behavior

The eval framework caches LLM results keyed by `{fixture_hash}_{code_hash}_{model}_{thinking_level}`:

- **Fixture changes** → cache miss (new fixture hash)
- **Prompt/schema changes** in `event_processing.py` → cache miss (new code hash)
- **Scoring-only changes** (thresholds, scorer logic) → cache HIT — the LLM output is the same, only the score changes. No need to re-run LLM calls; just re-score with `--use-cache`
- **Force re-run**: `--no-cache` ignores existing cache, `--clear-cache` deletes all cached results

---

## Baseline Tracking

After each significant change, save the markdown report:

```bash
uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/reports/YYYY-MM-DD-description.md
```

Naming convention: `{date}-{description}.md`
- `2026-02-20-post-scoring-fix.md`
- `2026-02-25-prompt-v2-no-hallucination.md`
- `2026-03-01-model-benchmark-q1.md`

This creates a historical record. Compare reports manually by diffing pass rates and failure lists.

Reports are saved in `backend/tests/eval/reports/` (gitignored results cache is in `backend/tests/eval/results/`).

---

## Decision Framework

When results are bad, use this to decide what to change:

| Observation | Likely Cause | Action |
|-------------|-------------|--------|
| Most models fail on a fixture | Fixture issue or prompt gap | Review fixture expected output; if correct, fix prompt |
| One model fails, others pass | Model limitation | Accept it, or switch default model |
| All fixtures in a category fail | Category-specific prompt gap | Add category-specific prompt instructions |
| Scores drop after code change | Regression | Revert or fix the code change |
| Scores are mediocre but stable | Prompt needs engineering | Iterative prompt improvement (Workflow A) |
| High PARTIAL, low FAIL | Scoring too strict | Review thresholds in `eval_config.py` |
| High FAIL, low PARTIAL | Fundamental extraction problems | Deep error analysis (Workflow D) |

---

## Current Gaps & Future Improvements

What the system doesn't do yet:

- **No automated baseline comparison** — report diffing is manual
- **No production data pipeline** — fixture creation from real failures is manual
- **No A/B prompt comparison CLI** — requires two separate runs and manual comparison
- **No threshold calibration tooling** — thresholds are hand-tuned in `eval_config.py`
- **No CI integration** — evals run locally only, not in the CI pipeline
