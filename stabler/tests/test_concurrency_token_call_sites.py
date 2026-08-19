"""Static guard: a caller of a concurrency-guarded endpoint must send the token.

`check_concurrency` (`stabler/api/_common.py:53-67`) is the only thing standing
between "the operator clicked Submit twice" and two postings. It works by
refusing a token the first completed call has already invalidated — `doc.submit()`
advances `modified`, so the repeat arrives stale and is thrown out.

That mechanism has a failure mode with no symptom on the server: a caller that
sends **no** token at all. On an existing document `check_concurrency` refuses a
missing token outright ("Stale request: reload the document."), so the endpoint
does not silently lose its guard — it stops working entirely. Measured
2026-08-20: three buttons in `hr/Employees.vue` had been dead since they were
written, and nobody noticed, because a dead button and a guarded button look the
same from the server side. The idempotency board found them by reading the code,
not from a bug report.

So this test pins the client half of the contract. It derives the guarded
endpoints from the API source itself rather than a hand-kept list — add an
unconditional `check_concurrency` to a whitelisted function and every literal
call site in the SPA is held to it from that moment on.

Not covered here, by construction rather than by omission: pages that route
submit/cancel/delete through `useDocumentForm`, which passes the token from the
loaded document (`useDocumentForm.js:178`, `:225`, `:277`). Those call sites
name the endpoint through a variable, so there is no literal for this scan to
find — and no way for a page to forget the token either.
"""

from __future__ import annotations

import ast
import glob
import os
import re
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler
_JS_ROOT = os.path.join(_APP_ROOT, "public", "js")


def _is_whitelist(dec: ast.expr) -> bool:
	d = dec.func if isinstance(dec, ast.Call) else dec
	return getattr(d, "attr", None) == "whitelist" or getattr(d, "id", None) == "whitelist"


def _calls_check_concurrency(stmt: ast.stmt) -> bool:
	if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
		return False
	fn = stmt.value.func
	return getattr(fn, "id", None) == "check_concurrency" or getattr(fn, "attr", None) == "check_concurrency"


def guarded_endpoints() -> set[str]:
	"""`stabler.api.<module>.<fn>` for every whitelisted fn that demands a token.

	Only *unconditional* calls count. `update_journal_entry` guards behind
	`if modified:` (`money.py:1277`) on purpose — its token is optional because
	the endpoint predates its caller — so it is not held to this rule.
	"""
	found: set[str] = set()
	for path in sorted(glob.glob(os.path.join(_APP_ROOT, "api", "*.py"))):
		tree = ast.parse(open(path, encoding="utf-8").read())
		module = f"stabler.api.{os.path.basename(path)[:-3]}"
		for node in tree.body:
			if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
				continue
			if not any(_is_whitelist(d) for d in node.decorator_list):
				continue
			if any(_calls_check_concurrency(s) for s in node.body):
				found.add(f"{module}.{node.name}")
	return found


def _call_argument_text(src: str, start: int) -> str:
	"""The text of the `call(...)` expression beginning at `start`, brace-matched.

	Reading only to end-of-line would report every multi-line payload in the SPA
	as a violation — four of the nine call sites are formatted that way.
	"""
	depth, i = 0, src.index("(", start)
	for j in range(i, len(src)):
		if src[j] == "(":
			depth += 1
		elif src[j] == ")":
			depth -= 1
			if depth == 0:
				return src[i : j + 1]
	return src[i:]


def call_sites() -> list[tuple[str, int, str, str]]:
	"""(file, line, endpoint, call text) for every literal `call("stabler.api…")`."""
	guarded = guarded_endpoints()
	out = []
	files = glob.glob(os.path.join(_JS_ROOT, "**", "*.vue"), recursive=True)
	files += glob.glob(os.path.join(_JS_ROOT, "**", "*.js"), recursive=True)
	for path in sorted(files):
		src = open(path, encoding="utf-8").read()
		for m in re.finditer(r'call\(\s*"([^"]+)"', src):
			if m.group(1) not in guarded:
				continue
			rel = os.path.relpath(path, os.path.dirname(_APP_ROOT))
			out.append(
				(rel, src[: m.start()].count("\n") + 1, m.group(1), _call_argument_text(src, m.start()))
			)
	return out


class EveryGuardedCallSendsItsToken(unittest.TestCase):
	def test_no_literal_call_site_omits_modified(self):
		"""A call without `modified` is not a weaker guard — it is a dead button.

		The failure is silent in the only place anyone looks: the server logs a
		refusal that reads exactly like a legitimate stale-token refusal.
		"""
		offenders = [f"{f}:{ln}  {ep}" for f, ln, ep, text in call_sites() if "modified" not in text]
		self.assertEqual(
			offenders,
			[],
			"These calls hit an endpoint that demands a concurrency token and send none.\n"
			"On an existing document the server answers 'Stale request: reload the document.'\n"
			"every single time — the button cannot work. Send `modified` from the loaded\n"
			"document, as `JournalEntries.vue:494` does:\n  " + "\n  ".join(offenders),
		)

	def test_the_scan_still_finds_something_to_check(self):
		"""Guards the guard: a regex that matches nothing passes vacuously.

		If `call(` is refactored away or the endpoints are renamed, the test above
		would go green while checking zero call sites. This keeps that honest.
		"""
		self.assertGreaterEqual(len(guarded_endpoints()), 20)
		self.assertGreaterEqual(len(call_sites()), 5)


if __name__ == "__main__":
	unittest.main()
