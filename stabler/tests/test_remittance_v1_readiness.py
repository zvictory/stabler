"""Saving a remittance configuration must refuse while nothing can protect its vouchers.

`_assert_ready_for_remittance` already refuses an empty cash-desk table, and its reason
generalises: a rollout that cannot do the job is not a rollout, so it is refused
when it is requested rather than at the counter with the customer present. One
precondition was missing from it, and the omission was not theoretical.

Measured on zuma, 2026-08-19. The site was created on 2026-08-14; Frappe stamps
every existing patch as applied when an app is installed on a fresh site, because
a fresh install is assumed to already carry the schema. That assumption holds for
DDL generated from doctype JSON. It does NOT hold for Custom Fields, which exist
only because patch code creates them — so `v33_remittance_stage_fields` was logged
as applied and created nothing. Journal Entry carried zero Custom Fields.

The consequence is silent, and it is the reason this gate exists:

* `remittance_accounting._build_entry` sets `stabler_remittance_id` on every stage
  voucher it inserts. Frappe drops a key that is not a field, without complaint,
  so all nine of zuma's remittance vouchers were written with none.
* `remittance_cancel_guard.assert_not_a_remittance_stage` opens with
  `doc.get("stabler_remittance_id")` and returns when it is empty — the cheap,
  selective exit that ordinary Journal Entries take. With the field absent, EVERY
  voucher takes it. The guard was registered, imported, and inert.

So V1 was switched on, took real transfers, and posted nine cancellable vouchers.
Nothing failed. Nothing logged. The guard's own test suite stayed green, because
it hands the handler a document that HAS the field.

This module closes that door at the only moment it can still be closed cheaply:
before the engine is turned on.

Bench-free: registered in `.github/frappe-free-tests.txt`, so it gates a push.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_remittance_v1_readiness -v
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_FAKED = (
	"stabler.api.remittance_settings",
	"stabler.api._common",
	"stabler.api.approvals",
	"frappe",
)

_SANDBOX = ModuleSandbox()

#: The two fields the cancel guard reads. Named here, not inlined, because the
#: point of the gate is that these exact names must exist on the site.
GUARD_FIELDS = ("stabler_remittance_id", "stabler_remittance_stage")


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


def _load(*, je_fields):
	"""Import the settings module against a Journal Entry meta carrying `je_fields`."""
	_SANDBOX.evict(*_FAKED)

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn

	class _Meta:
		def __init__(self, names):
			self._names = set(names)

		def get_field(self, fieldname):
			return types.SimpleNamespace(fieldname=fieldname) if fieldname in self._names else None

	frappe.get_meta = lambda doctype: _Meta(je_fields if doctype == "Journal Entry" else ())

	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: None
	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None

	_SANDBOX.install({"frappe": frappe, "stabler.api._common": common, "stabler.api.approvals": approvals})
	return importlib.import_module("stabler.api.remittance_settings")


def _doc(desks=1):
	return types.SimpleNamespace(
		company="Zuma",
		cash_desk_accounts=[{"branch": "Toshkent", "currency": "USD"}] * desks,
	)


class RemittanceReadinessTest(unittest.TestCase):
	"""Renamed from RemittanceReadinessTest with the gate itself.

	It ran only on the switch to V1 until the engine flag was retired on
	2026-08-20. Every assertion below is unchanged — none of them was ever about
	which engine asked, which is why the check survived the flag that triggered it.
	"""

	def test_v1_is_refused_when_the_guarded_fields_do_not_exist(self):
		"""The zuma state, exactly: the patch is logged, the fields are not there."""
		mod = _load(je_fields=())
		with self.assertRaises(_Thrown) as caught:
			mod._assert_ready_for_remittance(_doc())
		self.assertIn("stabler_remittance_id", str(caught.exception))

	def test_v1_is_refused_when_only_the_id_exists(self):
		"""Half the pair is not half a guard: the stage picks the refusal message,
		and the payout branch degrades silently to the milder one without it."""
		mod = _load(je_fields=("stabler_remittance_id",))
		with self.assertRaises(_Thrown) as caught:
			mod._assert_ready_for_remittance(_doc())
		self.assertIn("stabler_remittance_stage", str(caught.exception))

	def test_v1_is_allowed_once_both_fields_exist(self):
		mod = _load(je_fields=GUARD_FIELDS)
		mod._assert_ready_for_remittance(_doc())  # must not raise

	def test_the_empty_desk_table_is_still_refused(self):
		"""The rule this gate already carried stays first — a company with the
		fields but no desk still cannot register a transfer."""
		mod = _load(je_fields=GUARD_FIELDS)
		with self.assertRaises(_Thrown) as caught:
			mod._assert_ready_for_remittance(_doc(desks=0))
		self.assertIn("cash desk", str(caught.exception).lower())


class GuardFieldsAgreeWithTheGuardTest(unittest.TestCase):
	"""The gate is only worth anything while it names the fields the guard reads.

	Renaming one in `remittance_cancel_guard` and not here would leave every test
	in this file green and the guard inert again — the exact failure being fixed.
	"""

	def test_the_gate_names_every_field_the_cancel_guard_reads(self):
		import os
		import re

		src = os.path.join(
			os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
			"api",
			"remittance_cancel_guard.py",
		)
		with open(src, encoding="utf-8") as fh:
			read_by_guard = set(re.findall(r'doc\.get\(\s*"(stabler_[a-z_]+)"', fh.read()))
		self.assertTrue(read_by_guard, "the guard reads no stabler_ field — has it been rewritten?")

		# Three-way, and the SHIPPED constant is the one that matters. Comparing the
		# guard against this module's fixture alone would leave a renamed
		# `_GUARD_FIELDS` green — which is drift in the only direction that reopens
		# the hole.
		gate = set(_load(je_fields=())._GUARD_FIELDS)
		self.assertEqual(gate, read_by_guard, "the gate and the guard name different fields")
		self.assertEqual(gate, set(GUARD_FIELDS), "this module's fixture has drifted from the gate")


if __name__ == "__main__":
	unittest.main()
