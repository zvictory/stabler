# Stabler — the gate. `make check` is what .git/hooks/pre-push runs locally AND
# what the GitLab `lint`/`unit-tests` jobs shell out to, so there is exactly one
# definition of "green" and it cannot drift between laptop and CI.
#
# The GitHub workflow that used to mirror this was retired on 2026-07-27 — see
# .github/README.md. GitLab is the only pipeline.
#
# RATCHET, NOT BIG-BANG: the tree used to carry ~390 ruff violations and 273
# unformatted files. Linting all of it in the hook would have made the hook
# permanently red, and a permanently red hook is one everybody bypasses with
# --no-verify. So `check` lints only the files you touched: new code clean, old
# code cleaned when next edited.
#
# The Python debt reached ZERO on 2026-07-27 (rule by rule, then one formatting
# sweep), so for .py the changed-file scope is now a speed optimisation rather
# than a concession — `make lint` sweeps the whole tree and is expected green.
# The ratchet still earns its keep on the JS side, which is at 104 and falling.

RUFF_VERSION := $(shell cat .ruff-version)
# ?= so a different bench layout (or CI, which has no venv at this path) can
# override without editing the file. GitLab passes PY=python RUFF=ruff.
LOCAL_BENCH ?= /Users/zafar/frappe-bench-local
VENV ?= $(LOCAL_BENCH)/env/bin
RUFF ?= $(VENV)/ruff
PY   ?= $(VENV)/python

# Read-only drift check. Deploy is rsync WITHOUT --delete, so a file that ever
# reached prod stays there forever — including one-shot migration scripts that
# sit inside the importable package and can still be `bench execute`d. Nothing
# else notices them: .rsync-exclude governs what we SEND, not what is already
# THERE. This target only reports; deletion stays a deliberate, backed-up act.
PROD_HOST ?= ice-production
PROD_APP  ?= /home/frappe/frappe-bench/apps/stabler

# Files this push would introduce: everything since the last commit `origin`
# already has, plus anything uncommitted. --diff-filter=d drops deletions, which
# would otherwise be passed to ruff as nonexistent paths.
BASE := $(shell git merge-base HEAD origin/main 2>/dev/null || echo HEAD)
CHANGED_PY := $(shell { \
	git diff --name-only --diff-filter=d $(BASE) HEAD -- '*.py'; \
	git diff --name-only --diff-filter=d -- '*.py'; \
	git diff --cached --name-only --diff-filter=d -- '*.py'; \
	} 2>/dev/null | sort -u)
CHANGED_JS := $(shell { \
	git diff --name-only --diff-filter=d $(BASE) HEAD -- '*.js' '*.vue'; \
	git diff --name-only --diff-filter=d -- '*.js' '*.vue'; \
	git diff --cached --name-only --diff-filter=d -- '*.js' '*.vue'; \
	} 2>/dev/null | grep -v -e '^stabler/public/js/vendor/' -e '^stabler/public/dist/' | sort -u)

ESLINT := node_modules/.bin/eslint
PRETTIER := node_modules/.bin/prettier
VITEST := node_modules/.bin/vitest

.PHONY: help check lint lint-changed lint-js lint-js-changed fmt fix fix-js compile test test-bench test-js guards prod-drift ruff-install hook-install

help:
	@echo "make check         — pre-push gate: changed-file lint (py+js) + compile + guards + unit tests"
	@echo "make fix           — auto-fix + format the .py files you changed"
	@echo "make fix-js        — auto-fix + format the .js/.vue files you changed"
	@echo "make lint          — FULL tree lint (CI-equivalent; green as of 2026-07-27)"
	@echo "make lint-js       — FULL tree ESLint sweep (same, for the SPA)"
	@echo "make test          — the frappe-free unit modules only (no bench, no DB)"
	@echo "make test-bench    — the other 15 modules, on a throwaway site (slow, needs a bench)"
	@echo "make test-js       — Vitest over the SPA's pure-logic layer (composables/)"
	@echo "make guards        — CLAUDE.md hard rules (dates / Desk links / striping / tenant / money)"
	@echo "make prod-drift    — list .py/.json files on prod that are not in git (read-only)"
	@echo "make ruff-install  — pin ruff $(RUFF_VERSION) into the bench venv"
	@echo "make hook-install  — install .git/hooks/pre-push"

# ---------------------------------------------------------------- the gate ---

check: lint-changed lint-js-changed compile guards test test-js
	@echo "OK — pre-push gate passed."

# `ruff format --check` BLOCKS as of 2026-07-27. It was advisory for one reason:
# nothing in the tree had ever been formatted, so touching a big module rewrote
# ~200 lines and buried the one-line bugfix inside it. That sweep has now been
# done (517facd, 268 files, in .git-blame-ignore-revs), so the first touch of a
# module no longer reformats anything and the reason to look away is gone.
# `make fix` formats whatever this reports.
lint-changed:
ifeq ($(strip $(CHANGED_PY)),)
	@echo "ruff: no changed .py files, skipping."
else
	@echo "ruff: $(words $(CHANGED_PY)) changed file(s)"
	@$(RUFF) check $(CHANGED_PY)
	@$(RUFF) format --check $(CHANGED_PY)
endif

# Same ratchet, other language. 80k lines of Vue/JS had no static checking at
# all until 2026-07-27, so a typo in a <script setup> block only surfaced when a
# user opened the page — that is exactly how the missing `useRouter` import in
# PiGroups.vue and the missing `computed` import in OneCSyncLog.vue survived.
lint-js-changed:
ifeq ($(strip $(CHANGED_JS)),)
	@echo "eslint: no changed .js/.vue files, skipping."
else
	@if [ ! -x $(ESLINT) ]; then \
	  echo "eslint: node_modules missing — run 'npm install'."; \
	  echo "  (the GitLab 'eslint-debt' job covers the tree meanwhile)"; \
	else \
	  echo "eslint: $(words $(CHANGED_JS)) changed file(s)"; \
	  $(ESLINT) $(CHANGED_JS) || exit 1; \
	  $(PRETTIER) --check $(CHANGED_JS) >/dev/null 2>&1 || \
	    echo "  (prettier advisory -- 'make fix-js' formats these; not blocking)"; \
	fi
endif

fix:
ifeq ($(strip $(CHANGED_PY)),)
	@echo "no changed .py files."
else
	$(RUFF) check --fix $(CHANGED_PY)
	$(RUFF) format $(CHANGED_PY)
endif

fix-js:
ifeq ($(strip $(CHANGED_JS)),)
	@echo "no changed .js/.vue files."
else
	$(ESLINT) --fix $(CHANGED_JS)
	$(PRETTIER) --write $(CHANGED_JS)
endif

compile:
	@$(PY) -m compileall -q stabler

# -n1 = one module per process. This used to be load-bearing: several modules
# installed a fake `frappe` into sys.modules and never restored it, so a combined
# run leaked bare ModuleTypes into whichever module imported next. Every such
# module now goes through stabler/tests/module_sandbox.py and restores in
# tearDownModule, so isolation is no longer what keeps the suite green -- see the
# single-process pass below, which is what actually holds the line.
#
# -P8 is the one place this diverges from ci.yml: 84 interpreter startups are
# ~35s serial and ~7s at -P8. xargs still exits non-zero if any module fails;
# only the output interleaves.
#
# The second pass runs the SAME list in ONE interpreter, and is not redundant:
# `-P8 -n1` structurally cannot catch sys.modules pollution, because no leak ever
# crosses a module boundary there. That is exactly how four modules stayed green
# per-module while the combined run failed (measured 2026-08-14). It costs ~3s.
test:
	@echo "frappe-free modules: $$(grep -cv -e '^#' -e '^$$' .github/frappe-free-tests.txt)"
	@grep -v -e '^#' -e '^$$' .github/frappe-free-tests.txt | xargs -P8 -n1 $(PY) -m unittest
	@echo "single-process pass (sys.modules leak guard):"
	@grep -v -e '^#' -e '^$$' .github/frappe-free-tests.txt | xargs $(PY) -m unittest

# The OTHER 15. stabler/tests/ has 99 modules; the 84 above run without a bench,
# and the rest need a real site (they hit the DB, submit documents, check GL).
# Do not write the count here: BENCH_TESTS is derived and measured 50 on
# 2026-08-15, while every prose copy of it still said 15.
# The GitLab `bench-tests` job is supposed to cover them but is `when: manual` +
# `allow_failure: true` and has never once run, so its bootstrap is unproven.
# Proving them locally first is what earns that job the right to block.
#
# Not part of `check`: a bench run is ~minutes and needs a live MariaDB/Redis,
# which the pre-push hook must not depend on. Run it before a deploy instead.
#
# TEST_SITE defaults to the throwaway site, NOT the working `stabler` dev site:
# the runner creates and submits real documents. Override only if you mean it.
TEST_SITE ?= genesis-test.local
#
# Derived, not hardcoded: "every test module that is NOT in the frappe-free
# list". A hardcoded list of 15 goes stale the first time someone adds a test.
# awk rather than `comm <(...)`: process substitution is bash-only and make
# runs recipes under /bin/sh.
# (sed uses | as its delimiter, not #: this is a variable assignment, and make
# would treat a bare # as the start of a comment and eat the rest of the line.)
BENCH_TESTS := $(shell ls stabler/tests/test_*.py | sed 's|.*/||; s|\.py$$||' | sort \
	| awk 'NR==FNR{sub(/^stabler\.tests\./,"");free[$$0]=1;next} !($$0 in free)' \
	    .github/frappe-free-tests.txt -)

test-bench:
	@$(PY) -c "import json,sys; c=json.load(open('$(LOCAL_BENCH)/sites/$(TEST_SITE)/site_config.json')); \
	 sys.exit(0 if c.get('allow_tests') else 1)" \
	 || { echo "ERROR: $(TEST_SITE) has allow_tests off (or does not exist)."; \
	      echo "  bench --site $(TEST_SITE) set-config allow_tests true"; exit 1; }
	@echo "bench modules: $(words $(BENCH_TESTS))  site: $(TEST_SITE)"
	@fail=0; mute=0; muted=""; log=`mktemp`; \
	for m in $(BENCH_TESTS); do \
	  echo "--- $$m"; \
	  ( cd $(LOCAL_BENCH) && bench --site $(TEST_SITE) run-tests \
	      --module stabler.tests.$$m ) > $$log 2>&1 || fail=1; \
	  cat $$log; \
	  ran=`sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' $$log | tail -1`; \
	  skip=`sed -n 's/.*(skipped=\([0-9][0-9]*\)).*/\1/p' $$log | tail -1`; \
	  [ -n "$$ran" ] || ran=0; [ -n "$$skip" ] || skip=0; \
	  if [ "$$ran" -eq 0 ]; then \
	    echo "!! ZERO COVERAGE: $$m collected no tests on $(TEST_SITE)."; \
	    mute=`expr $$mute + 1`; muted="$$muted $$m(collected-none)"; \
	  elif [ "$$skip" -eq "$$ran" ]; then \
	    echo "!! ZERO COVERAGE: $$m skipped all $$ran tests on $(TEST_SITE) -- nothing was asserted."; \
	    mute=`expr $$mute + 1`; muted="$$muted $$m(skipped-$$ran/$$ran)"; \
	  fi; \
	done; \
	rm -f $$log; \
	if [ "$$mute" != "0" ]; then \
	  echo ""; \
	  echo "ZERO COVERAGE: $$mute of $(words $(BENCH_TESTS)) modules asserted nothing --$$muted"; \
	  echo "  A module that skips every test still prints OK, so the run reads as proof it is not."; \
	  echo "  Three causes, all seen here: an optional app is missing on $(TEST_SITE) (install it, THEN"; \
	  echo "  replay that app's dependent stabler patches -- see the TEST_SITE comment); the site has no"; \
	  echo "  seeded fixture the module needs; or a test class that does not subclass TestCase, which"; \
	  echo "  unittest cannot collect at all."; \
	  fail=1; \
	fi; \
	if [ "$$fail" != "0" ]; then \
	  echo "FAIL: a bench module is red or proved nothing -- see the --- and !! markers above."; fi; \
	exit $$fail

# Vitest over the SPA's pure-logic layer. Scope is deliberately narrow: the
# composables (money, date, status, i18n) plus the api/ wrapper -- no component
# mounting, no jsdom. Those four modules are where the CLAUDE.md hard rules
# actually live (money grouping, dd.mm.yyyy, central status badges), and they are
# the only part of 80k lines of Vue that can be asserted without a browser.
#
# Same graceful skip as lint-js-changed: the GitLab `gate` job runs on a python
# image with no node. THAT is why the `js-tests` job exists on the node image --
# without it this step would silently pass in CI and the gate would be a lie.
test-js:
	@if [ ! -x $(VITEST) ]; then \
	  echo "vitest: node_modules missing — run 'npm install'."; \
	  echo "  (the GitLab 'js-tests' job covers this meanwhile)"; \
	else \
	  $(VITEST) run; \
	fi

# CLAUDE.md states these as "reviewers must reject". Prose does not enforce.
#
# Notes on the four rules added 2026-07-27 (the recipe below is one joined shell
# command, so these cannot live inline -- a `#` there would comment out the rest):
#
#  * RAW DATES: the `\.` in the pattern is load-bearing. Without it the regex also
#    matches the word "creation" inside translated prose -- KassaBot.vue:336 was
#    the false positive that taught us this. Property access only.
#  * TENANT NAMES: 7 tenants share this code, so behaviour must come from Stabler
#    Company Modules, never a hardcoded site name. At zero today; this keeps it there.
#  * meta.module: a parent route with children[] and no meta.module is invisible to
#    the router guard, so a disabled module stays reachable by direct URL. Zero today.
#  * MONEY INPUTS: a hard ZERO as of 2026-07-27, no longer a ceiling. The last 9
#    were cleared once the precision worry turned out to be unfounded: MoneyInput
#    rounds only the BLURRED DISPLAY (format()), while the model keeps the value
#    the user typed, and focus re-shows it in full via rawText(). So a step=0.0001
#    rate loses nothing. The UZS-forces-0-decimals trap is real but avoidable --
#    rate fields simply pass no `currency` prop, so integer mode never engages.
#    The -v filter below drops percentage fields (duty_rate_pct, vat_rate_pct):
#    they matched only because "rate" is a substring. A percent is not money, and
#    MoneyInput would render a 12% rate as "12,00" in money styling.
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
	hits=$$(grep -rnE '\{\{[^}]*\.(posting_date|transaction_date|due_date|creation|modified|schedule_date|valid_till|start_date|end_date)\b[^}]*\}\}' \
	         stabler/public/js --include='*.vue' | grep -vE 'formatDate|formatTime' || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: raw date interpolation -- wrap in formatDate()/formatDateTime()/formatTime()"; \
	  echo "$$hits"; fail=1; fi; \
	hits=$$(grep -rnE '(==|!=|===|!==)[[:space:]]*["'"'"'](anjan|msa|mikas|dts|horeca|laminor|smartbox)' \
	         stabler --include='*.py' --include='*.vue' --include='*.js' \
	         | grep -v node_modules || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: branching on tenant name -- gate on a module/company setting instead"; \
	  echo "$$hits"; fail=1; fi; \
	miss=$$(awk '/children:[[:space:]]*\[/ {w=""; for(i=NR-6;i<=NR;i++) w=w " " L[i]; \
	          if (w !~ /module:/) print NR": "L[NR-3]} {L[NR]=$$0}' \
	          stabler/public/js/router.js || true); \
	if [ -n "$$miss" ]; then \
	  echo "ERROR: parent route with children[] and no meta.module (router guard is blind to it)"; \
	  echo "$$miss"; fail=1; fi; \
	hits=$$(grep -rn --include='*.vue' -B3 'type="number"' stabler/public/js \
	     | grep -E 'v-model[^"]*"[^"]*(rate|amount|price|paid|balance|salary|advance)[^"]*"' \
	     | grep -vE 'v-model[^"]*"[^"]*(_pct|_percent|percentage)[^"]*"' || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: bare <input type=\"number\"> for money -- use MoneyInput"; \
	  echo "$$hits"; fail=1; fi; \
	exit $$fail

# Lists .py and .json files that exist in prod's package but not in git. Run
# after every deploy. Exit 1 on drift so it can be scripted; it never touches
# the server.
#
# .json is in scope as of 2026-07-27, and it was added because the .py-only
# version missed something real. Clearing the five stray scripts turned up a
# sixth orphan the report had never mentioned:
# stabler/doctype/stabler_company_modules/stabler_company_modules.json — a
# doctype definition sitting outside the module directory, invisible purely
# because of its extension. A doctype is a .json file; a drift check that only
# reads .py cannot see a stale doctype, which is the more dangerous of the two.
#
# Measured before widening: 83 .json on prod, exactly one not in git — the
# orphan above. So the extra scope costs no noise, given the dist/ exclusion
# (build output, gitignored by design).
#
# Both sides are scoped to stabler/ so the comparison is symmetric: package.json
# and .prettierrc.json live at the repo root, outside the tree `find` walks.
prod-drift:
	@tmp=$$(mktemp -d); \
	git ls-files -- 'stabler/*.py' 'stabler/*.json' | sort > $$tmp/local; \
	ssh $(PROD_HOST) "cd $(PROD_APP) && find stabler -type f \
	    \( -name '*.py' -o -name '*.json' \) \
	    -not -path '*/node_modules/*' -not -path '*/__pycache__/*' \
	    -not -path 'stabler/public/dist/*'" \
	  | sort > $$tmp/prod; \
	if [ ! -s $$tmp/prod ]; then \
	  echo "prod-drift: ABORT — prod listesi boş (ssh koptu mu?). Boş liste her"; \
	  echo "  zaman 'temiz' görünür; bu bir sonuç değil, ölçüm hatasıdır."; \
	  rm -rf $$tmp; exit 1; \
	fi; \
	extra=$$(comm -13 $$tmp/local $$tmp/prod); \
	rm -rf $$tmp; \
	if [ -n "$$extra" ]; then \
	  echo "DRIFT: $$(echo "$$extra" | wc -l | tr -d ' ') file(s) on prod are not in git:"; \
	  echo "$$extra" | sed 's/^/  /'; \
	  echo "Review before deleting: back up, list with ls, then remove."; \
	  exit 1; \
	fi; \
	echo "prod-drift: clean — no untracked .py/.json under $(PROD_APP)/stabler"

# ------------------------------------------------------- whole-tree sweeps ---

# No leading `-`: both of these are at zero as of 2026-07-27 (345 violations and
# 268 unformatted files, paid off rule by rule), so a failure here is a real
# regression rather than the standing debt it used to be. `lint-js` keeps its
# `-` because the JS side still carries a ceiling of 104.
lint:
	$(RUFF) check stabler
	$(RUFF) format --check stabler

lint-js:
	-$(ESLINT) stabler/public/js
	-$(PRETTIER) --check stabler/public/js

fmt:
	$(RUFF) format stabler

# ------------------------------------------------------------------ setup ---

# Unpinned `pip install ruff` is how a green gate turns red overnight: a new
# ruff release adds rules (RUF059 alone is 98 hits here) and nothing changed in
# our code. The pin lives in .ruff-version — ONE file, read by both this Makefile
# and .gitlab-ci.yml, so the two can no longer drift apart silently.
ruff-install:
	$(VENV)/pip install -q 'ruff==$(RUFF_VERSION)'
	@$(RUFF) --version

hook-install:
	@printf '#!/bin/sh\n# installed by `make hook-install` -- see Makefile\nexec make -C "$$(git rev-parse --show-toplevel)" check\n' \
	  > .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "installed .git/hooks/pre-push (bypass with git push --no-verify)"
