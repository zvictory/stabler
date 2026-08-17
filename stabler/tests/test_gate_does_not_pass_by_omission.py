"""A verification gate must fail when it cannot check, never pass by omission.

Frappe-free: the Makefile is read as text, the same structural technique as
`test_gate_sees_new_files.py` and `test_imports_api_invariants.py`.

Sibling of that module and the same defect family — the DoD command reporting
success on something it never opened — but the other half of it. That one is
about files the gate could not SEE. This one is about checks the gate could not
RUN, and answered by printing a note and exiting 0.

Three of them were live, all measured 2026-08-17:

  1. `lint-js-changed` and `test-js` each tested `[ ! -x <tool> ]`, echoed
     "node_modules missing", and exited 0. A fresh `git worktree add` has no
     node_modules, and the orchestration skill prescribes exactly that worktree
     for every delegated implementation — so `make check` printed
     "OK — pre-push gate passed" with two of its six gates switched off. Proved
     by putting an unterminated call in a .vue file and watching it through a
     clean run; with node_modules present the same file fails eslint. Since most
     of what a delegated agent writes here is Vue, that was the majority of a
     delegated diff going unlinted and untested. The skip is correct on the
     GitLab python image and nowhere else, hence the `$CI` test.

  2. `make test-bench` run from a worktree measured the MAIN tree. The recipe
     does `cd $(LOCAL_BENCH) && bench run-tests`, and the bench venv resolves
     the `stabler` package through `stabler.pth`, which points at the main tree.
     Proved with a probe module visible only in the worktree: unittest found it,
     the bench raised ModuleNotFoundError. A silent false pass, on exactly the
     beads whose DoD is `make test-bench` because money moves in them.

  3. Two concurrent `make test-bench` runs collided (stabler-w2dd). One bench,
     one pinned site, one database: both processes run `before_tests`, and
     fixtures.py raised "cannot unpack non-iterable NoneType object" — a FIXTURE
     failure, which is why the six "flaky" modules all passed when run alone.

Structural, not behavioural, for the reason `test_gate_sees_new_files` gives:
a behavioural test would shell out to `make`, need a live bench for two of the
three, and mutate the tree it runs in. Each assertion below pins one way the fix
can be reverted while still looking plausible in a diff. The behavioural
reproduction of all three was run by hand when the fix landed.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

MAKEFILE = os.path.normpath(os.path.join(_ROOT, "..", "Makefile"))


#: `ifeq`/`else`/`endif` also sit at column 0, so "the next column-0 line" ends a
#: recipe one line early on every conditional target — and `lint-js-changed` is
#: one. Extracting an empty body would make every assertion below vacuously fail
#: rather than silently pass, but it would still be measuring nothing.
_CONDITIONAL = r"ifeq|ifneq|ifdef|ifndef|else|endif"


def _recipe(source: str, target: str) -> str:
	"""One Makefile recipe: the target line to the next column-0 declaration."""
	match = re.search(
		rf"^{re.escape(target)}:.*?\n(.*?)(?=^(?!{_CONDITIONAL})\S)",
		source,
		re.MULTILINE | re.DOTALL,
	)
	if not match or not match.group(1).strip():
		raise AssertionError(f"no `{target}:` recipe body in {MAKEFILE}")
	return match.group(1)


class TheJsGatesRefuseRatherThanSkip(unittest.TestCase):
	"""Missing node_modules must be a red gate everywhere except CI."""

	def setUp(self) -> None:
		with open(MAKEFILE, encoding="utf-8") as handle:
			self.source = handle.read()

	def test_lint_js_only_skips_under_ci(self) -> None:
		recipe = _recipe(self.source, "lint-js-changed")
		# The skip branch must be conditioned on CI. Without the condition it is
		# the unconditional pass that let a syntactically invalid .vue file
		# through a green `make check`.
		self.assertRegex(recipe, r'\[\s*-n\s*"\$\$CI"\s*\]')
		self.assertIn("exit 1;", recipe)

	def test_test_js_only_skips_under_ci(self) -> None:
		recipe = _recipe(self.source, "test-js")
		self.assertRegex(recipe, r'\[\s*-n\s*"\$\$CI"\s*\]')
		self.assertIn("exit 1;", recipe)

	def test_both_gates_name_the_fix(self) -> None:
		# The failure has exactly one remedy in a worktree and a different one in
		# a fresh clone, and an agent that hits this message must not have to
		# guess. `npm ci` is deliberately NOT offered: the tracked lockfile is out
		# of sync with package.json and it exits 1.
		for target in ("lint-js-changed", "test-js"):
			recipe = _recipe(self.source, target)
			with self.subTest(target=target):
				self.assertIn("ln -s", recipe)
				self.assertIn("npm install", recipe)
				self.assertNotIn("npm ci", recipe)


class TestBenchRefusesToMeasureTheWrongTree(unittest.TestCase):
	def setUp(self) -> None:
		with open(MAKEFILE, encoding="utf-8") as handle:
			self.source = handle.read()
		self.recipe = _recipe(self.source, "test-bench")

	def test_it_compares_this_tree_against_the_bench_tree(self) -> None:
		self.assertIn("git rev-parse --show-toplevel", self.recipe)
		self.assertIn("$(LOCAL_BENCH)/apps/stabler", self.recipe)
		# `pwd -P` on both sides, or a symlinked apps/stabler — which is an
		# ordinary bench layout — compares unequal and refuses a legitimate run.
		self.assertEqual(2, self.recipe.count("pwd -P"))

	def test_the_refusal_precedes_any_bench_invocation(self) -> None:
		# Ordering is the whole assertion. A guard that runs after the loop has
		# already produced the false measurement it exists to prevent. Same shape
		# as test_imports_api_invariants' `for_update=True` position check.
		guard = self.recipe.index("REFUSING: test-bench cannot measure this tree")
		run = self.recipe.index("bench --site $(TEST_SITE) run-tests")
		self.assertLess(guard, run)

	def test_it_takes_a_lock_before_running_anything(self) -> None:
		lock = self.recipe.index('mkdir "$$lock"')
		run = self.recipe.index("bench --site $(TEST_SITE) run-tests")
		self.assertLess(lock, run)
		# Released on every exit path, including the failing ones — a ratchet
		# violation is the common outcome, and a lock leaked there blocks every
		# later run until someone deletes a directory they have never heard of.
		self.assertRegex(self.recipe, r"trap '.*rmdir \$\$lock")

	def test_it_reports_the_sha_it_measured(self) -> None:
		# stabler-w2dd: "a test-bench report without a SHA is not evidence." Both
		# ends, because the head of a 53-module run has scrolled away by the time
		# the verdict prints.
		self.assertIn("git rev-parse --short HEAD", self.recipe)
		self.assertIn("measuring:", self.recipe)
		# DOTALL: the trap body is wrapped across a continuation, and the closing
		# report deliberately lives inside it rather than after the ratchet — a
		# ratchet violation exits early, and that is the run whose sha is most
		# worth having.
		self.assertTrue(
			re.search(r"trap '.*?measured: ", self.recipe, re.DOTALL),
			"the EXIT trap no longer reports the measured sha",
		)


class TheRatchetParsesTheStrippedLog(unittest.TestCase):
	"""stabler-c1a6: colour hid `(skipped=N)` and a skip-everything module read green."""

	def setUp(self) -> None:
		with open(MAKEFILE, encoding="utf-8") as handle:
			self.recipe = _recipe(handle.read(), "test-bench")

	def test_coverage_is_parsed_from_the_stripped_copy(self) -> None:
		for name in ("ran=", "skip="):
			line = next(ln for ln in self.recipe.splitlines() if ln.strip().startswith(name))
			with self.subTest(field=name):
				self.assertIn("$$clean", line)
				# Reading $$log again is the exact regression: frappe writes
				# `ESC[32mOK ESC[0m (ESC[33mskipped=3 ESC[0m)`, the literal
				# `(skipped=` never appears, skip falls back to 0, and a module
				# that asserted nothing counts as a pass.
				self.assertNotIn("$$log", line)

	def test_the_human_still_sees_the_colour(self) -> None:
		# Stripping is for the parser only. `cat $$log` keeps the coloured output
		# a person reads; stripping that too would be a second, silent change.
		self.assertRegex(self.recipe, r"cat \$\$log")

	def test_the_escape_is_a_real_control_character(self) -> None:
		# BSD sed does not interpret `\x1b`, so a literal-escape pattern written
		# for GNU sed silently matches nothing on macOS — which is where this
		# gate is actually run.
		self.assertIn("printf '\\033'", self.recipe)
		self.assertNotIn(r"\x1b", self.recipe)


if __name__ == "__main__":
	unittest.main()
