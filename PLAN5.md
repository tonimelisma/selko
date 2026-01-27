# PLAN5: Auto-Merge Configuration Issue

## Problem

When attempting to enable auto-merge on PRs with `gh pr merge --auto --squash`, the command fails with:

```
GraphQL: Pull request Protected branch rules not configured for this branch (enablePullRequestAutoMerge)
```

## Root Cause

Auto-merge requires branch protection rules to be configured on the repository. Currently, the `main` branch does not have protection rules enabled that allow auto-merge.

## Solution

Configure branch protection rules in GitHub repository settings:

1. Go to **Settings** → **Branches** → **Add branch protection rule**
2. Set **Branch name pattern**: `main`
3. Enable the following:
   - ☑️ **Require a pull request before merging**
   - ☑️ **Require status checks to pass before merging**
     - Select required status checks (e.g., CI workflow)
   - ☑️ **Allow auto-merge**
4. Save changes

## Alternative Workflows

Until auto-merge is configured, PRs can be merged manually:

```bash
# After CI passes, merge manually
gh pr merge --squash

# Or merge from GitHub web UI
```

## Impact on CLAUDE.md

The current documentation in `CLAUDE.md` and `docs/parallel-agents.md` instructs:

```bash
gh pr create && gh pr merge --auto --squash
```

This will fail until branch protection is configured. Options:

1. **Configure branch protection** (recommended) - enables the documented workflow
2. **Update documentation** to use manual merge until protection is configured

## References

- GitHub docs: [Managing auto-merge](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)
- GitHub docs: [Branch protection rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)
