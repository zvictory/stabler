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
#
# The fourth line — `git ls-files --others` — is untracked files, and leaving it
# out cost a rejected push on 2026-08-16. The three `git diff` forms see commits,
# unstaged tracked changes and the index; a brand-new file is in none of them, so
# a micro-task that ADDS a module (the normal shape of a new frappe-free one) ran
# this gate with ruff seeing zero of the new code and printing "no changed .py
# files, skipping" — green, exit 0, on code it never opened. The first `git push`
# then ran the same target on the now-committed files and failed. The failure
# hides only for a file's first commit, which is exactly when it is least
# reviewed. --exclude-standard keeps .gitignore'd build output out.
BASE := $(shell git merge-base HEAD origin/main 2>/dev/null || echo HEAD)
CHANGED_PY := $(shell { \
	git diff --name-only --diff-filter=d $(BASE) HEAD -- '*.py'; \
	git diff --name-only --diff-filter=d -- '*.py'; \
	git diff --cached --name-only --diff-filter=d -- '*.py'; \
	git ls-files --others --exclude-standard -- '*.py'; \
	} 2>/dev/null | sort -u)
CHANGED_JS := $(shell { \
	git diff --name-only --diff-filter=d $(BASE) HEAD -- '*.js' '*.vue'; \
	git diff --name-only --diff-filter=d -- '*.js' '*.vue'; \
	git diff --cached --name-only --diff-filter=d -- '*.js' '*.vue'; \
	git ls-files --others --exclude-standard -- '*.js' '*.vue'; \
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
	@echo "make test-bench    — every module NOT in the frappe-free list, on a throwaway site (slow, needs a bench)"
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
	@if [ ! -x $(ESLINT) ] && [ -n "$$CI" ]; then \
	  echo "eslint: node_modules missing — run 'npm install'."; \
	  echo "  (the GitLab 'eslint-debt' job covers the tree meanwhile)"; \
	elif [ ! -x $(ESLINT) ]; then \
	  echo "eslint: node_modules missing, and $(words $(CHANGED_JS)) .js/.vue file(s) changed."; \
	  echo "  This gate does not pass by omission. Measured 2026-08-17: a fresh"; \
	  echo "  'git worktree add' has no node_modules, so a .vue file containing an"; \
	  echo "  unterminated call went through 'make check' and printed"; \
	  echo "  'OK — pre-push gate passed'. Two of six gates were off and it said so"; \
	  echo "  in a line nobody reads. The graceful skip above is for the GitLab"; \
	  echo "  python image only, which is why it now tests \$$CI."; \
	  echo "  Fix with ONE of:"; \
	  echo "    ln -s $(LOCAL_BENCH)/apps/stabler/node_modules node_modules   # in a worktree"; \
	  echo "    npm install                                                   # in a fresh clone"; \
	  exit 1; \
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
# -P8 is the one place this diverges from ci.yml: one interpreter startup per
# module in the list, which is the whole cost here. Measured 2026-07-27 at the
# size the list was then: ~35s serial, ~7s at -P8. xargs still exits non-zero if
# any module fails; only the output interleaves.
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

# Everything the frappe-free list does NOT name. Those run without a bench; the
# rest need a real site (they hit the DB, submit documents, check GL).
#
# No count belongs in this comment. Three used to live here -- 15, 84, 99 -- and
# all three were wrong by the time anyone read them, because a count is a
# snapshot of a set that changes every time someone adds a test. Name the set and
# the command instead: `make test-bench` prints how many it derived, every run.
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
# list". A hardcoded list goes stale the first time someone adds a test.
# awk rather than `comm <(...)`: process substitution is bash-only and make
# runs recipes under /bin/sh.
# (sed uses | as its delimiter, not #: this is a variable assignment, and make
# would treat a bare # as the start of a comment and eat the rest of the line.)
BENCH_TESTS := $(shell ls stabler/tests/test_*.py | sed 's|.*/||; s|\.py$$||' | sort \
	| awk 'NR==FNR{sub(/^stabler\.tests\./,"");free[$$0]=1;next} !($$0 in free)' \
	    .github/frappe-free-tests.txt -)

# The ratchet. When the ZERO COVERAGE check above made this gate honest, five
# modules went red at once. Demanding all five green before anything may proceed
# would make the gate permanently red -- and this Makefile already recorded, at
# the top, what happens then: "a permanently red hook is one everybody bypasses
# with --no-verify."
#
# So the gate is red against a BASELINE, not against zero, and it is enforced in
# BOTH directions. Four ways to fail, because a ratchet that only checks one
# direction is a list, not a mechanism:
#
#   NEW RED      a module is red and is not listed        -- you broke something
#   NOW GREEN    a listed module passes                   -- delete its line
#   STALE ENTRY  a listed module left BENCH_TESTS         -- renamed or deleted
#   NO BEAD      a line with no bead id in field 2        -- then it is not tracked
#
# STALE ENTRY is the one that is easy to leave out and the one that rots the file:
# rename a module and it silently drops out of both the observed set and the
# derived set, so the other three checks all agree nothing is wrong while the
# baseline quietly shrinks.
#
# The site pin is parsed, not prose. Two of the five entries are red only because
# genesis-test.local lacks an app or a fixture; on a richer site they pass, NOW
# GREEN fires, and the ratchet deletes its own baseline. So a pin mismatch
# disables the ratchet entirely and every red counts.
# The log is PARSED with ANSI stripped and DISPLAYED with the colour intact. When
# frappe colourises, the line is `ESC[32mOK ESC[0m (ESC[33mskipped=3 ESC[0m)`, so
# the literal `(skipped=` the pattern needs never appears, `skip` falls back to 0,
# and a module that skipped every one of its tests counts GREEN — restoring exactly
# the lie 44fe689 removed when it made zero coverage red. Measured 2026-08-17
# (stabler-c1a6): two runs of one commit on one site, opposite verdicts. Stripping
# beats NO_COLOR because it protects every future pattern too, and the human still
# reads the coloured `cat`, not the parse.
#
# The lock and the tree guard are one defect seen from two sides, and neither is
# tidiness. There is one bench, one site and one code path. Two concurrent runs
# both execute before_tests against the same database, and fixtures.py:145 raises
# `cannot unpack non-iterable NoneType object` — a FIXTURE failure, which is why
# the "six modules that flip between runs" (stabler-w2dd) all passed when run
# alone. Held under one session the same six were identical across three trees.
# And because `bench` resolves `stabler` through stabler.pth to the MAIN tree, a
# run started from a worktree measures main and reports it as the branch.
#
# One module CAN be iterated from a worktree -- PYTHONPATH is consulted before
# stabler.pth, so `PYTHONPATH=<worktree> bench run-tests --module ...` imports
# that worktree's PYTHON (measured 2026-08-21: mutate a guard there and only the
# PYTHONPATH run goes red; without it the same tree stays green). That is an
# inner loop, not this gate, and it does NOT weaken either guard above. It takes
# no lock, so it can land mid-run of the target below. And it measures python,
# never SCHEMA: doctype meta comes from the site's already-migrated DB, where a
# worktree-only doctype raises but a worktree-only FIELD is dropped SILENTLY --
# insert() succeeds and the value vanishes. Full caveats: stabler-orchestrator s3.
KNOWN_RED := .github/bench-known-red.txt

test-bench:
	@$(PY) -c "import json,sys; c=json.load(open('$(LOCAL_BENCH)/sites/$(TEST_SITE)/site_config.json')); \
	 sys.exit(0 if c.get('allow_tests') else 1)" \
	 || { echo "ERROR: $(TEST_SITE) has allow_tests off (or does not exist)."; \
	      echo "  bench --site $(TEST_SITE) set-config allow_tests true"; exit 1; }
	@here=`git rev-parse --show-toplevel 2>/dev/null || pwd`; \
	here=`cd "$$here" && pwd -P`; \
	main_tree=`cd $(LOCAL_BENCH)/apps/stabler 2>/dev/null && pwd -P`; \
	if [ "$$here" != "$$main_tree" ]; then \
	  echo "REFUSING: test-bench cannot measure this tree."; \
	  echo "  you are in : $$here"; \
	  echo "  bench reads: $$main_tree"; \
	  echo ""; \
	  echo "  This target does 'cd $(LOCAL_BENCH) && bench run-tests', and the bench"; \
	  echo "  venv resolves the 'stabler' package through stabler.pth, which points"; \
	  echo "  at the main tree. So from a worktree or a second clone it imports MAIN's"; \
	  echo "  code and reports the verdict as if it were this branch's — a silent"; \
	  echo "  false pass, on exactly the branches where money moves. Verified 2026-08-17"; \
	  echo "  with a probe module visible only in the worktree: unittest found it,"; \
	  echo "  the bench raised ModuleNotFoundError."; \
	  echo ""; \
	  echo "  Merge the branch into the main tree and run it there, or check the"; \
	  echo "  branch out in $$main_tree. There is no flag to override this gate."; \
	  echo ""; \
	  echo "  To ITERATE one module from a worktree -- never to gate on it --"; \
	  echo "  invoke bench directly with PYTHONPATH set to the worktree root, so"; \
	  echo "  imports resolve there instead of through stabler.pth. That measures"; \
	  echo "  the worktree PYTHON but NOT its SCHEMA: doctype meta still comes"; \
	  echo "  from this site, where a worktree-only FIELD is dropped SILENTLY --"; \
	  echo "  insert succeeds and the value vanishes. It also skips the sweep,"; \
	  echo "  the ZERO COVERAGE check and the ratchet, and it takes NO lock."; \
	  echo "  Exact command and caveats: stabler-orchestrator skill, section 3."; \
	  exit 1; \
	fi
	@obs=`mktemp`; known=`mktemp`; derived=`mktemp`; tmp=`mktemp`; live=`mktemp`; log=`mktemp`; clean=`mktemp`; \
	sha=`git rev-parse --short HEAD`; br=`git rev-parse --abbrev-ref HEAD`; \
	dirty=`git status --porcelain --untracked-files=no | wc -l | tr -d ' '`; \
	untr=`git ls-files --others --exclude-standard -- stabler | grep '\.py$$' | wc -l | tr -d ' '`; \
	lock=$(LOCAL_BENCH)/.stabler-test-bench.lock; \
	if ! mkdir "$$lock" 2>/dev/null; then \
	  echo "REFUSING: another test-bench run holds $$lock (pid `cat $$lock/pid 2>/dev/null || echo '?'`)."; \
	  echo "  One bench, one site, one code path — two concurrent runs measure each"; \
	  echo "  other. That is stabler-w2dd: the 'six modules flip between runs' was"; \
	  echo "  never test flakiness. Both processes run before_tests against the same"; \
	  echo "  site, and fixtures.py:145 raises 'cannot unpack non-iterable NoneType'"; \
	  echo "  — a FIXTURE failure, which is why the same modules pass when run alone."; \
	  echo "  Wait for the other run. If it is dead, remove the directory by hand."; \
	  rm -f $$obs $$known $$derived $$tmp $$live $$log $$clean; \
	  exit 1; \
	fi; \
	echo $$$$ > "$$lock/pid"; \
	trap 'rm -f $$obs $$known $$derived $$tmp $$live $$log $$clean; rm -f $$lock/pid; rmdir $$lock 2>/dev/null; \
	      echo ""; echo "measured: $$br @ $$sha on $(TEST_SITE)"' EXIT; \
	echo "bench modules: $(words $(BENCH_TESTS))  site: $(TEST_SITE)"; \
	echo "measuring:     $$br @ $$sha"; \
	[ "$$dirty" = "0" ] || echo "               WARNING: $$dirty modified tracked file(s) — this sha does not describe what ran."; \
	[ "$$untr" = "0" ] || echo "               WARNING: $$untr untracked .py file(s) under stabler/ — collected by this run, absent from that sha."; \
	esc=`printf '\033'`; \
	for m in $(BENCH_TESTS); do \
	  echo "--- $$m"; \
	  red=0; \
	  ( cd $(LOCAL_BENCH) && bench --site $(TEST_SITE) run-tests \
	      --module stabler.tests.$$m ) > $$log 2>&1 || red=1; \
	  cat $$log; \
	  sed -E "s/$${esc}\[[0-9;]*m//g" $$log > $$clean; \
	  ran=`sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' $$clean | tail -1`; \
	  skip=`sed -n 's/.*(skipped=\([0-9][0-9]*\)).*/\1/p' $$clean | tail -1`; \
	  [ -n "$$ran" ] || ran=0; [ -n "$$skip" ] || skip=0; \
	  if [ "$$ran" -eq 0 ]; then \
	    echo "!! ZERO COVERAGE: $$m collected no tests on $(TEST_SITE)."; red=1; \
	  elif [ "$$skip" -eq "$$ran" ]; then \
	    echo "!! ZERO COVERAGE: $$m skipped all $$ran tests on $(TEST_SITE) -- nothing was asserted."; red=1; \
	  fi; \
	  [ "$$red" = "0" ] || echo "$$m" >> $$obs; \
	done; \
	sort -u -o $$obs $$obs; \
	for m in $(BENCH_TESTS); do echo "$$m"; done | sort > $$derived; \
	if [ ! -f $(KNOWN_RED) ]; then \
	  echo "FAIL: $(KNOWN_RED) is missing. Without a baseline every red is red -- restore it or re-measure."; \
	  exit 1; \
	fi; \
	pin=`sed -n 's/^#pin site=//p' $(KNOWN_RED) | head -1`; \
	if [ -z "$$pin" ]; then \
	  echo "FAIL: $(KNOWN_RED) has no '#pin site=' line, so it does not say what it was measured on."; \
	  exit 1; \
	fi; \
	awk '!/^#/ && NF' $(KNOWN_RED) > $$tmp; \
	awk '{print $$1}' $$tmp | sort > $$known; \
	fail=0; \
	nobead=`awk 'NF < 2 {print $$1}' $$tmp`; \
	if [ -n "$$nobead" ]; then \
	  echo ""; \
	  for m in $$nobead; do \
	    echo "NO BEAD: $$m -- an entry with no bead is not known-red, it is ignored. Add the bead id."; \
	  done; \
	  fail=1; \
	fi; \
	stale=`comm -23 $$known $$derived`; \
	if [ -n "$$stale" ]; then \
	  echo ""; \
	  for m in $$stale; do \
	    echo "STALE ENTRY: $$m is listed in $(KNOWN_RED) but is not a bench module any more."; \
	    echo "  Renamed, deleted, or moved to .github/frappe-free-tests.txt. Delete its line."; \
	  done; \
	  fail=1; \
	fi; \
	if [ "$$pin" != "$(TEST_SITE)" ]; then \
	  echo ""; \
	  echo "RATCHET DISABLED: the baseline is pinned to $$pin, this run used $(TEST_SITE)."; \
	  echo "  A red set measured on one site says nothing about another, so every red counts here."; \
	  echo "  Re-measure and re-pin if you meant to move sites."; \
	  if [ -s $$obs ]; then \
	    sed 's/^/  red: /' $$obs; fail=1; \
	  fi; \
	  if [ "$$fail" != "0" ]; then \
	    echo "FAIL: bench is red -- see the --- and !! markers above."; fi; \
	  exit $$fail; \
	fi; \
	new=`comm -13 $$known $$obs`; \
	if [ -n "$$new" ]; then \
	  echo ""; \
	  for m in $$new; do \
	    echo "NEW RED: $$m is red and is not in $(KNOWN_RED)."; \
	    echo "  You broke it -- or it was always broken and needs a bead and a line in that file."; \
	  done; \
	  fail=1; \
	fi; \
	comm -12 $$known $$derived > $$live; \
	fixed=`comm -23 $$live $$obs`; \
	if [ -n "$$fixed" ]; then \
	  echo ""; \
	  for m in $$fixed; do \
	    echo "NOW GREEN: $$m passes but is still listed in $(KNOWN_RED) -- delete its line."; \
	  done; \
	  echo "  The set only tightens. An entry that has started passing is as red as a new failure,"; \
	  echo "  because a baseline nobody prunes stops being a baseline and becomes an excuse."; \
	  fail=1; \
	fi; \
	if [ "$$fail" != "0" ]; then \
	  echo ""; \
	  echo "FAIL: the known-red ratchet was violated -- see the messages above."; \
	  exit 1; \
	fi; \
	if [ -s $$obs ]; then \
	  echo ""; \
	  echo "ratchet OK: `wc -l < $$obs | tr -d ' '` red, all of them known and beaded, none newly green."; \
	  sed 's/^/  /' $$obs; \
	  echo "  Known-red is not green. These are debts recorded in $(KNOWN_RED), not passes."; \
	fi


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
	@if [ ! -x $(VITEST) ] && [ -n "$$CI" ]; then \
	  echo "vitest: node_modules missing — run 'npm install'."; \
	  echo "  (the GitLab 'js-tests' job covers this meanwhile)"; \
	elif [ ! -x $(VITEST) ]; then \
	  echo "vitest: node_modules missing, so this gate asserted nothing."; \
	  echo "  Skipping is correct on the GitLab python image and nowhere else —"; \
	  echo "  hence the \$$CI test. Locally it means the suite did not run at all."; \
	  echo "  Fix with ONE of:"; \
	  echo "    ln -s $(LOCAL_BENCH)/apps/stabler/node_modules node_modules   # in a worktree"; \
	  echo "    npm install                                                   # in a fresh clone"; \
	  exit 1; \
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
	hits=$$(grep -rnE 'UZS.*\?.*(\b0\b[[:space:]]*:|Math\.round)' stabler/public/js \
	         --include='*.vue' --include='*.js' \
	         | grep -v 'composables/money.js' || true); \
	if [ -n "$$hits" ]; then \
	  echo "ERROR: a second opinion on how many decimals UZS has -- ask moneyFractionDigits()"; \
	  echo "$$hits"; fail=1; fi; \
	exit $$fail

# Lists .py, .json and .vue files that exist in prod's package but not in git.
# Run after every deploy. Exit 1 on drift so it can be scripted; it never
# touches the server.
#
# The extension list is written THREE times below — the git pathspecs, the
# find predicates, and the success message the operator reads. Widening one and
# not the others makes the check report less than it claims;
# stabler/tests/test_prod_drift_scope.py refuses that.
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
#
# .vue is in scope as of 2026-08-20. rsync deploys without --delete, so a
# renamed or deleted component leaves its old copy on prod forever — and the
# check the operator is told to run after every deploy (deploy_stabler.sh:312)
# said "clean". The functional risk is low, because router.js registers routes
# statically and an orphaned component is never served; the reason to see it
# anyway is that this report is the only place anyone would ever find out.
#
# .js is deliberately NOT in scope. Prod carries build output and locally
# gitignored js, and this target exits 1 on any extra — so including it would
# make the check red on every run, which teaches the operator to skip the one
# thing they are told to run after every deploy. A documented gap beats a check
# the team has learned to ignore.
prod-drift:
	@tmp=$$(mktemp -d); \
	git ls-files -- 'stabler/*.py' 'stabler/*.json' 'stabler/*.vue' | sort > $$tmp/local; \
	ssh $(PROD_HOST) "cd $(PROD_APP) && find stabler -type f \
	    \( -name '*.py' -o -name '*.json' -o -name '*.vue' \) \
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
	echo "prod-drift: clean — no untracked .py/.json/.vue under $(PROD_APP)/stabler"

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
