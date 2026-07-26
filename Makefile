# Stabler — local gate. Mirrors .github/workflows/ci.yml job `lint-and-unit`.
#
# WHY THIS EXISTS: GitHub Actions has run exactly once (2026-07-09, failed).
# `main` is ~194 commits ahead of `github/main`, so that workflow has not
# inspected a single line of the last three weeks' work. Until CI is wired to
# the remote we actually push to, this Makefile IS the gate.
#
# `make check` is what .git/hooks/pre-push runs.
#
# RATCHET, NOT BIG-BANG: the tree carries ~390 pre-existing ruff violations and
# 273 files that `ruff format` would rewrite. Linting all of it in the hook
# would make the hook permanently red, and a permanently red hook is a hook
# everybody bypasses with --no-verify. So `check` lints only the files you
# touched: new code is clean, old code gets cleaned when it is next edited.
# `make lint` still runs the full CI-equivalent sweep when you want the number.

RUFF_VERSION := 0.16.0
VENV := /Users/zafar/frappe-bench-local/env/bin
RUFF := $(VENV)/ruff
PY   := $(VENV)/python

# Files this push would introduce: everything since the last commit `origin`
# already has, plus anything uncommitted. --diff-filter=d drops deletions, which
# would otherwise be passed to ruff as nonexistent paths.
BASE := $(shell git merge-base HEAD origin/main 2>/dev/null || echo HEAD)
CHANGED_PY := $(shell { \
	git diff --name-only --diff-filter=d $(BASE) HEAD -- '*.py'; \
	git diff --name-only --diff-filter=d -- '*.py'; \
	git diff --cached --name-only --diff-filter=d -- '*.py'; \
	} 2>/dev/null | sort -u)

.PHONY: help check lint lint-changed fmt fix compile test guards ruff-install hook-install

help:
	@echo "make check         — pre-push gate: changed-file lint + compile + guards + unit tests"
	@echo "make fix           — auto-fix + format the files you changed"
	@echo "make lint          — FULL tree lint (CI-equivalent; currently red, that is the debt)"
	@echo "make test          — the frappe-free unit modules only (no bench, no DB)"
	@echo "make guards        — CLAUDE.md hard rules (date input / Desk links / table-striped)"
	@echo "make ruff-install  — pin ruff $(RUFF_VERSION) into the bench venv"
	@echo "make hook-install  — install .git/hooks/pre-push"

# ---------------------------------------------------------------- the gate ---

check: lint-changed compile guards test
	@echo "OK — pre-push gate passed."

lint-changed:
ifeq ($(strip $(CHANGED_PY)),)
	@echo "ruff: no changed .py files, skipping."
else
	@echo "ruff: $(words $(CHANGED_PY)) changed file(s)"
	@$(RUFF) check $(CHANGED_PY)
	@# Format is ADVISORY, not a gate. Nothing here was ever `ruff format`ed, so
	@# the first touch of a big module rewrites ~200 lines (purchasing.py: 215).
	@# Blocking on that buries every one-line bugfix in formatting noise and makes
	@# a production rollback harder to read. Run `make fmt` + a
	@# .git-blame-ignore-revs entry as one deliberate sweep instead.
	@$(RUFF) format --check $(CHANGED_PY) || \
	  echo "  (advisory only -- 'make fix' formats these; not blocking the push)"
endif

fix:
ifeq ($(strip $(CHANGED_PY)),)
	@echo "no changed .py files."
else
	$(RUFF) check --fix $(CHANGED_PY)
	$(RUFF) format $(CHANGED_PY)
endif

compile:
	@$(PY) -m compileall -q stabler

# -n1 = one module per process, deliberately: several modules install a fake
# `frappe` into sys.modules and never restore it, so a combined run leaks
# MagicMocks into whichever module imports next. Same reasoning as CI.
#
# -P8 is the one place this diverges from ci.yml: 84 interpreter startups are
# ~35s serial and ~7s at -P8. Safe precisely BECAUSE of -n1 -- the modules share
# no process state, which is why they had to be isolated in the first place.
# xargs still exits non-zero if any module fails; only the output interleaves.
test:
	@echo "frappe-free modules: $$(grep -cv -e '^#' -e '^$$' .github/frappe-free-tests.txt)"
	@grep -v -e '^#' -e '^$$' .github/frappe-free-tests.txt | xargs -P8 -n1 $(PY) -m unittest

# CLAUDE.md states these as "reviewers must reject". Prose does not enforce.
guards:
	@fail=0; \
	hits=$$(grep -rn 'type="date"' stabler/public/js --include='*.vue' \
	         | grep -v 'components/DateInput.vue' || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: bare <input type=\"date\"> is banned -- use DateInput.vue"; \
	  echo "$$hits"; fail=1; fi; \
	hits=$$(grep -rnE '["'"'"'`]/app/' stabler/public/js --include='*.vue' || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: Frappe Desk link (/app/...) is banned -- build the CRUD inside Stabler"; \
	  echo "$$hits"; fail=1; fi; \
	hits=$$(grep -rn 'table-striped' stabler/public/js --include='*.vue' || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: manual table-striped is redundant -- striping is global in stabler.css"; \
	  echo "$$hits"; fail=1; fi; \
	exit $$fail

# ------------------------------------------------------- whole-tree sweeps ---

lint:
	-$(RUFF) check stabler
	-$(RUFF) format --check stabler

fmt:
	$(RUFF) format stabler

# ------------------------------------------------------------------ setup ---

# Unpinned `pip install ruff` is how a green gate turns red overnight: a new
# ruff release adds rules (RUF059 alone is 98 hits here) and nothing changed in
# our code. Pin here and in ci.yml; bump both together, deliberately.
ruff-install:
	$(VENV)/pip install -q 'ruff==$(RUFF_VERSION)'
	@$(RUFF) --version

hook-install:
	@printf '#!/bin/sh\n# installed by `make hook-install` -- see Makefile\nexec make -C "$$(git rev-parse --show-toplevel)" check\n' \
	  > .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "installed .git/hooks/pre-push (bypass with git push --no-verify)"
