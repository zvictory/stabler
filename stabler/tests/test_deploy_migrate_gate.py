"""`scripts/migrate_gate.sh` decides whether prod's 7 sites get a `bench migrate`.

The module is written against `unittest`, not pytest, and that is load-bearing
rather than taste: nothing in this repo runs pytest. `make test-bench` invokes
`bench run-tests --module`, which collects `unittest.TestCase` subclasses only,
so the pytest-style bare class this file used to declare collected ZERO tests
while reporting OK. It sat in `.github/bench-known-red.txt` as
`stabler-56v  ZERO COVERAGE, collected-none` for exactly that reason — five
docstrings describing five guarantees, none of which was ever checked.

What is being guarded: the gate is trusted asymmetrically. It is fail-safe about
what it does not KNOW (an empty or unreachable stamp migrates), but it trusts a
confident "no triggers" completely — and the "Skipping migrate" branch advances
prod's stamp anyway (`deploy_stabler.sh:266`), so a wrong "not needed" is not a
deferred migrate, it is a permanent one. The symptom surfaces later and
elsewhere: a tenant crashing on a column that was never created.
"""

from __future__ import annotations

import functools
import os
import pathlib
import subprocess
import tempfile
import unittest

_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_APP_DIR, "scripts", "migrate_gate.sh")

# Two commits from this repo's history, used as fixtures because the gate's whole
# job is reading real diffs. b16e03b touches a .vue file only; c519ddc edits a
# doctype JSON. `GIT_DEPTH: "0"` in .gitlab-ci.yml keeps both reachable in CI.
_VUE_ONLY_COMMIT = "b16e03b"
_DOCTYPE_COMMIT = "c519ddc"


def _run_gate(cmd: str, app_dir: str = _APP_DIR) -> subprocess.CompletedProcess:
	"""Source the gate library and evaluate `cmd` against `app_dir`.

	`APP_DIR` is passed explicitly rather than inherited from the cwd: the gate
	functions resolve their repo from it, and the runners start in different
	places (`bench run-tests` from the bench root, `make test` from the app root).
	It is also what lets the classification tests point the real function at a
	throwaway repo instead of restating its regex.
	"""
	env = os.environ.copy()
	env["APP_DIR"] = app_dir
	return subprocess.run(
		["bash", "-c", f"source '{_SCRIPT}'; {cmd}"],
		capture_output=True,
		text=True,
		env=env,
		cwd=app_dir,
	)


def _verdict(from_sha: str, to_ref: str) -> subprocess.CompletedProcess:
	return _run_gate(f"if migrate_needed '{from_sha}' '{to_ref}'; then echo NEEDED; else echo NOT_NEEDED; fi")


class TheGateReadsTheDiff(unittest.TestCase):
	"""The confident half: a verdict derived from files that really changed."""

	def test_a_release_touching_only_vue_does_not_migrate(self):
		"""Skipping is the point of the gate — a `migrate` on 7 sites is not free.

		b16e03b changes a Vue file and nothing schema-relevant, so classifying it
		as NEEDED would mean the gate never skips anything and the stamp
		machinery exists for nothing.
		"""
		result = _verdict(f"{_VUE_ONLY_COMMIT}~1", _VUE_ONLY_COMMIT)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("NOT_NEEDED", result.stdout)

	def test_a_release_touching_a_doctype_migrates(self):
		"""The expensive direction. c519ddc edits `proforma_invoice.json`.

		A missed doctype change ships a column that exists in the code and in no
		tenant's database, and because the skip branch advances prod's stamp the
		next deploy diffs against a commit that already contains it — the change
		is invisible to the gate forever.
		"""
		trigger = _run_gate(f"migrate_trigger_files {_DOCTYPE_COMMIT}~1 {_DOCTYPE_COMMIT}")
		self.assertEqual(trigger.returncode, 0, trigger.stderr)
		self.assertEqual(
			trigger.stdout.strip(),
			"stabler/stabler/doctype/proforma_invoice/proforma_invoice.json",
			"the doctype JSON must be named as the trigger, not merely counted",
		)

		result = _verdict(f"{_DOCTYPE_COMMIT}~1", _DOCTYPE_COMMIT)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("NEEDED", result.stdout)

	def test_deploying_the_commit_already_on_prod_does_not_migrate(self):
		"""from == to is the steady state: a re-run of a deploy that changed nothing.

		The diff is empty, so the answer must come from the diff being empty and
		not from a fallback — this is the one case that proves the confident
		branch is reachable at all.
		"""
		result = _verdict("HEAD", "HEAD")
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("NOT_NEEDED", result.stdout)


class TheGateMigratesWhenItCannotKnow(unittest.TestCase):
	"""The fail-safe half, and the reason each fallback prints WHY on stderr.

	A silent `NEEDED` is indistinguishable from a real trigger, so the deploy log
	could never tell "the schema changed" from "the stamp was unreadable". The
	stderr assertions below are what keep the two apart.
	"""

	def test_a_missing_stamp_migrates(self):
		"""First deploy after the stamp file is introduced, or after it is lost.

		Unknown previous state means the schema could be anything; assuming it
		matches is the one assumption that breaks all 7 tenants at once.
		"""
		result = _verdict("", "HEAD")
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("NEEDED", result.stdout)
		self.assertIn("migrate_needed fallback: from_sha is empty", result.stderr)

	def test_a_stamp_this_clone_has_never_seen_migrates(self):
		"""Prod is not a git repo, so its stamp can name a commit we do not have —
		a force-push, a rewritten branch, or simply a clone that is behind.

		Without the commit there is no diff to read, so there is nothing to be
		confident about.
		"""
		unknown = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
		result = _verdict(unknown, "HEAD")
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("NEEDED", result.stdout)
		self.assertIn(
			f"migrate_needed fallback: from_sha '{unknown}' is not a commit reachable in this repo",
			result.stderr,
		)


class EveryScheduleMutatingPathIsClassified(unittest.TestCase):
	"""The regex in `migrate_trigger_files` is the thing that must not drift.

	This drives the real function over a throwaway repo rather than restating its
	pattern here. A copy of the regex in the test is worse than no test: it drifts
	from the script and stays green while the gate stops classifying something.
	Each path is asserted separately because the alternatives were added at
	different times for different reasons, and a single "does it match anything"
	check would keep passing after one of them was dropped.
	"""

	TRIGGERS = (
		# Where every DDL this app performs actually lives.
		"stabler/patches/v96_money_idempotency_key.py",
		# An entry here is how a patch gets run at all.
		"stabler/patches.txt",
		"stabler/stabler/doctype/proforma_invoice/proforma_invoice.json",
		# Custom fields are DDL too -- they add real columns to ERPNext tables.
		"stabler/custom/sales_invoice.json",
		# Carries `fixtures` and doc_events; migrate re-reads it.
		"stabler/hooks.py",
		"stabler/fixtures/custom_field.json",
	)

	# The negative controls. Without them every assertion above would still pass
	# against a regex that matched everything, and the gate would never skip.
	INERT = (
		"stabler/public/js/pages/money/JournalEntries.vue",
		"stabler/api/money.py",
		"stabler/stabler/doctype/proforma_invoice/proforma_invoice.py",
		"README.md",
	)

	@classmethod
	def setUpClass(cls):
		cls._tmp = tempfile.TemporaryDirectory()
		repo = cls._tmp.name
		run = functools.partial(subprocess.run, cwd=repo, check=True, capture_output=True)
		run(["git", "init", "-q", "-b", "main"])
		run(["git", "config", "user.email", "gate@test.local"])
		run(["git", "config", "user.name", "gate"])
		(pathlib.Path(repo) / "seed").write_text("seed\n")
		run(["git", "add", "seed"])
		run(["git", "commit", "-qm", "seed"])
		for rel in cls.TRIGGERS + cls.INERT:
			path = pathlib.Path(repo) / rel
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text("x\n")
		run(["git", "add", *cls.TRIGGERS, *cls.INERT])
		run(["git", "commit", "-qm", "one release touching everything"])
		cls._classified = set(_run_gate("migrate_trigger_files HEAD~1 HEAD", app_dir=repo).stdout.split())

	@classmethod
	def tearDownClass(cls):
		cls._tmp.cleanup()

	def test_every_schema_mutating_path_is_named_as_a_trigger(self):
		for rel in self.TRIGGERS:
			with self.subTest(path=rel):
				self.assertIn(rel, self._classified)

	def test_no_inert_path_is_named_as_a_trigger(self):
		for rel in self.INERT:
			with self.subTest(path=rel):
				self.assertNotIn(rel, self._classified)


if __name__ == "__main__":
	unittest.main()
