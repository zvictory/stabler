"""Undo the ``sys.modules`` fakes a bench-free test module plants.

Most tests here run without a bench by dropping a hand-built ``types.ModuleType``
into ``sys.modules`` under a real name (``frappe``, ``stabler.api._common``, …)
and then importing the module under test against it. That is fine on its own.
What is not fine is leaving the stub behind: ``sys.modules`` is process-wide, so
every module that runs *later in the same process* imports the stub instead of
the real thing. A bare ``ModuleType`` has no ``__file__``, which is why the
victim's traceback reads ``cannot import name X from Y (unknown location)`` —
the failure surfaces in a test that never touched the fake.

Measured 2026-08-14: six modules leaked this way, and the full frappe-free
registry run failed with 4 errors in modules that were individually green.
``make check`` cannot catch it — it runs ``xargs -P8 -n1``, one module per
process, so no leak ever crosses a module boundary there.

Restoring right after ``importlib.import_module`` is NOT a safe alternative:
``stabler/api/crm.py`` and ``stabler/api/tender.py`` import ``frappe.utils`` and
friends *inside* their functions, so the fakes have to still be in place when
the tests call them. The correct scope is the test module — hence ``restore()``
from ``tearDownModule()``.

Usage::

    _SANDBOX = ModuleSandbox()

    def _load_api(...):
        _SANDBOX.evict("stabler.api.crm", "frappe", "frappe.utils")
        ...
        _SANDBOX.install({"frappe": frappe, "frappe.utils": utils})
        return importlib.import_module("stabler.api.crm")

    def tearDownModule():
        _SANDBOX.restore()
"""

from __future__ import annotations

import sys
from types import ModuleType

__all__ = ["ModuleSandbox"]


class ModuleSandbox:
	"""Records the real ``sys.modules`` entries a test module overwrites."""

	def __init__(self) -> None:
		self._saved: dict[str, ModuleType | None] = {}

	def _remember(self, name: str) -> None:
		# First write wins: a loader called once per test must not record its own
		# fake from the previous call as the thing to restore.
		if name not in self._saved:
			self._saved[name] = sys.modules.get(name)

	def evict(self, *names: str) -> None:
		"""Drop these names so the next import rebuilds them against the fakes."""
		for name in names:
			self._remember(name)
			sys.modules.pop(name, None)

	def install(self, modules: dict[str, ModuleType]) -> None:
		"""Publish fake modules, remembering whatever they displace."""
		for name in modules:
			self._remember(name)
		sys.modules.update(modules)

	def restore(self) -> None:
		"""Put ``sys.modules`` back exactly as it was before the first evict."""
		for name, module in self._saved.items():
			if module is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = module
		self._saved.clear()
