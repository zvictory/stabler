# This directory is not a CI config

CI for Stabler runs on **GitLab**, not GitHub. The pipeline lives in
`.gitlab-ci.yml` at the repo root.

`origin` is `git@gitlab.com:zvictory2001/stabler.git`; the GitHub remote is a
mirror that lags behind and has no active pipeline.

## Why the workflow was removed

`.github/workflows/ci.yml` last ran on 2026-07-09 and went red. It was written
when the tree was lint-clean; today a full-tree sweep is 386 ruff errors and 273
unformatted files, so the job would fail on every push regardless of the change
being pushed. Two CI definitions that can disagree about what "green" means is
worse than one — the GitLab pipeline is the one that actually gates pushes (see
the pre-push hook), so the GitHub copy was retired rather than kept in a
permanently-red state.

The old workflow is still in git history (`git log -- .github/workflows/ci.yml`)
if the GitHub pipeline is ever revived. Its `bench-tests` job — bench init +
MariaDB/Redis services + throwaway site — was ported to the `bench-tests` job in
`.gitlab-ci.yml`, so nothing was lost.

## What stays here

`frappe-free-tests.txt` — the list of test modules that run without a bench.
It is **not** GitHub-specific: `make test` (`Makefile:83`) and the GitLab
`unit-tests` job both read it. The path stayed put so neither had to change.
