"""A test module that fakes ``frappe`` must hand ``sys.modules`` back.

This guards one measured failure, not a style preference.

Six modules installed a fake ``frappe`` into ``sys.modules`` and never restored
it. Their own tests passed and printed ``OK``. Then ``bench run-tests`` ran its
``_cleanup_after_tests``, which calls ``frappe.clear_cache()``, found a
``types.ModuleType("frappe")`` with no ``cache`` attribute, and exited 1 --
*after* the suite had already reported success.

That combination is the worst shape a test can have: the words say pass, the
exit code says fail, and which one you believe depends on whether anything
downstream bothers to check. Nothing did, for as long as ``make test-bench``
collapsed every non-zero module into a single opaque ``Error 1``. The known-red
ratchet is what finally surfaced it.

``unittest`` runs ``tearDownModule`` per module. A module that imports another
module's ``_load_api`` borrows a process-wide sandbox and inherits the duty to
hand it back -- the owner's ``tearDownModule`` does not run on the borrower's
behalf. That inheritance is invisible at the import site, which is exactly why
it needs a mechanical check rather than a convention.

  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_module_sandbox_hygiene -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent

# Ways a module can put a fake `frappe` (or a fake stabler.api.*) into sys.modules:
# writing the key directly, publishing through ModuleSandbox, or borrowing a
# loader that does one of those on its behalf.
_FAKES = re.compile(
	r"""sys\.modules\[["']frappe["']\]\s*=      # direct assignment
	  | \bSANDBOX\.install\(                      # published via the sandbox
	  | ^from\s+stabler\.tests\.\w+\s+import\s+.*\b_load_api\b   # borrowed loader
	""",
	re.M | re.X,
)

# Two accepted ways to give it back: the sandbox's teardown, or a hand-rolled
# finally that reassigns sys.modules (test_seed_tender_demo predates the sandbox
# and does exactly this -- correctly).
_RESTORES = re.compile(
	r"""^def\s+tearDownModule\b        # unittest's per-module hook
	  | ^\s*finally:                     # or a hand-rolled restore
	""",
	re.M | re.X,
)


def _module_sources():
	for path in sorted(_TESTS.glob("test_*.py")):
		if path.name == Path(__file__).name:
			continue
		yield path, path.read_text(encoding="utf-8")


class TestEveryFrappeFakerHandsItBack(unittest.TestCase):
	def test_a_module_that_fakes_frappe_defines_a_teardown(self):
		"""The check that would have caught stabler-5gc the day it was written."""
		offenders = [
			path.name for path, src in _module_sources() if _FAKES.search(src) and not _RESTORES.search(src)
		]
		self.assertEqual(
			offenders,
			[],
			"These test modules install a fake `frappe` into sys.modules and never "
			"restore it. Their tests will pass and `bench run-tests` will still exit "
			"non-zero, because frappe's own _cleanup_after_tests calls "
			"frappe.clear_cache() on the fake. Add:\n\n"
			"    from stabler.tests.module_sandbox import ModuleSandbox\n"
			"    _SANDBOX = ModuleSandbox()\n\n"
			"    def tearDownModule():\n"
			"        _SANDBOX.restore()\n\n"
			"and publish the fakes with _SANDBOX.install({...}) / _SANDBOX.evict(...) "
			f"instead of assigning sys.modules directly. Offenders: {offenders}",
		)

	def test_the_guard_can_actually_fail(self):
		"""A guard nobody has seen fail is not a guard.

		Both halves matter: the detector must fire on a faker, and the restore
		pattern must switch it off. Asserting only the first would pass even if
		`_RESTORES` matched everything.
		"""
		faker = 'sys.modules["frappe"] = types.ModuleType("frappe")\n'
		self.assertTrue(_FAKES.search(faker))
		self.assertFalse(_RESTORES.search(faker))

		borrowed = "from stabler.tests.test_sourcing_api import _FakeFrappe, _load_api\n"
		self.assertTrue(_FAKES.search(borrowed), "a borrowed loader must count as faking")

		self.assertTrue(_RESTORES.search(faker + "def tearDownModule():\n\tpass\n"))
		self.assertTrue(_RESTORES.search(faker + "try:\n\tpass\nfinally:\n\tpass\n"))

	def test_the_scan_actually_reaches_the_modules_it_claims_to(self):
		"""Guards against the scan silently matching nothing.

		If the glob or the path ever breaks, every assertion above passes
		vacuously — an empty offender list looks identical to a clean tree.
		"""
		fakers = [path.name for path, src in _module_sources() if _FAKES.search(src)]
		self.assertGreater(len(fakers), 5, f"expected the fake-frappe family to be found, saw {fakers}")
