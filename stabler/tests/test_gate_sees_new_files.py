"""The push gate must lint files it has never seen before.

Frappe-free: the Makefile is read as text.

Measured on 2026-08-16, and it cost a rejected push. `CHANGED_PY` was built from
three `git diff` forms — commits since the merge-base, unstaged tracked changes,
and the index. A brand-new file is in none of them. So a micro-task that ADDS a
module, which is the normal shape of a new frappe-free one, ran `make check` with
ruff seeing zero of the new code: it printed "no changed .py files, skipping" and
exited 0. The bead was closed on that evidence. The first `git push` then ran the
same target on the now-committed files and failed on RUF012 and two format diffs.

That is the dangerous kind of failure — the DoD command reporting success on code
it never opened — and it hides only for a file's first commit, which is exactly
when a new module is least reviewed. It recurred on 2026-08-17 during
stabler-qzr9.9 and was only avoided by staging the new files by hand before
running the gate.

A behavioural test would have to shell out to `make`, create a deliberately
broken file in the working tree and assert a red exit. That is slow, and it
mutates the tree it is running in. The structural assertion below is the same
one the repo already makes elsewhere (`test_desk_gate_setting.py`,
`test_imports_api_invariants.py`): pin the source so a later refactor cannot
quietly drop the line. The behavioural reproduction was run once, by hand, when
the fix landed — untracked file with an F841, gate went from exit 0 to exit 2.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

MAKEFILE = os.path.normpath(os.path.join(_ROOT, "..", "Makefile"))

#: The fourth source. `--exclude-standard` is not decoration: without it the
#: gate would lint .gitignore'd build output and go red on `dist/`.
UNTRACKED = "git ls-files --others --exclude-standard"


def _brace_group(source: str, variable: str) -> str:
	"""The `$(shell { ... })` body of one Makefile variable."""
	match = re.search(
		rf"^{re.escape(variable)}\s*:=\s*\$\(shell\s*\{{(.*?)\}}\s*2>/dev/null",
		source,
		re.MULTILINE | re.DOTALL,
	)
	if not match:
		raise AssertionError(
			f"{variable} is no longer a `$(shell {{ ... }} 2>/dev/null)` group in {MAKEFILE}. "
			"If the shape changed deliberately, this test has to change with it — but the "
			"untracked-file source still has to be in there."
		)
	return match.group(1)


class TheGateSeesUntrackedFiles(unittest.TestCase):
	def setUp(self) -> None:
		with open(MAKEFILE, encoding="utf-8") as handle:
			self.source = handle.read()

	def test_changed_py_includes_untracked(self) -> None:
		group = _brace_group(self.source, "CHANGED_PY")
		self.assertIn(UNTRACKED, group)
		# Inside the group, not merely somewhere in the file: a line that sits
		# outside the brace group contributes nothing to the variable and would
		# leave the gate exactly as blind as before.
		self.assertRegex(group, rf"{re.escape(UNTRACKED)}\s+--\s+'\*\.py'")

	def test_changed_js_includes_untracked(self) -> None:
		group = _brace_group(self.source, "CHANGED_JS")
		self.assertIn(UNTRACKED, group)
		self.assertRegex(group, rf"{re.escape(UNTRACKED)}\s+--\s+'\*\.js'\s+'\*\.vue'")

	def test_all_four_sources_are_present(self) -> None:
		# Dropping any one of them re-opens a blind spot: HEAD..merge-base misses
		# work in progress, the unstaged form misses staged work, the cached form
		# misses unstaged work, and untracked misses new files entirely.
		for variable in ("CHANGED_PY", "CHANGED_JS"):
			group = _brace_group(self.source, variable)
			with self.subTest(variable=variable):
				self.assertIn("git diff --name-only --diff-filter=d $(BASE) HEAD", group)
				self.assertIn("git diff --cached --name-only --diff-filter=d", group)
				self.assertIn(UNTRACKED, group)
				self.assertEqual(4, len([ln for ln in group.splitlines() if "git " in ln]))


if __name__ == "__main__":
	unittest.main()
