# 0014. A merge to main releases to production through a signed image

- Status: accepted
- Date: 2026-11-28

## Context and problem

Hand deploys and deploy credentials in CI were sources of drift. The server should run only an
image CI built and checked from main. Requirements: [SEL-687](../requirements/operations.md).

## Decision drivers

- No manual step between merge and production.
- No deploy credential in CI.
- The server verifies what it runs.

## Considered options

### CI builds and checks the image, a release workflow cosign-signs it keylessly and moves `:main`; the server follows `:main` and verifies the signature (chosen)

- Good: the tested image is the deployed image; no secret.
- Bad: a bad merge reaches production within minutes.
- Failure modes: a rename of the workflow or move of the signing job breaks verification on the server.

### Push-based deploys from CI

- Good: explicit.
- Bad: CI holds production credentials.
- Failure modes: a leaked token deploys anything.

## Decision

Workflow `CI` (`.github/workflows/ci.yml`) builds the image and runs `scripts/image-lane.sh`; on a
push to main that touches the image's inputs it pushes `ghcr.io/tonimelisma/selko:<sha>`. Workflow
`Image` (`.github/workflows/image.yml`) runs when CI succeeds for that push: its `release` job
cosign-signs the digest (identity `.github/workflows/image.yml@refs/heads/main`) and moves `:main`;
its `health` job polls `https://api.selkoapp.com/health` until it answers with that commit and runs
`scripts/check-production-health.sh`, opening a `deploy-failure` issue on failure.

## Consequences

Merging is releasing: never merge red. One-off production data operations (a data cutover,
anything that deletes or rewrites production data) are not part of this flow and need an explicit
yes from the maintainer. Never rename `image.yml` or move its signing job.

## Confirmation

`backend/tests/test_gate_contract.py` (SEL-687) for the image's inputs; the `health` job on every
release.

## Retirement proof

A release mechanism with the same verification on the server, shown by a signed release the
server accepts.

## Reversal plan

Pin the server to a known digest and stop following `:main`.
